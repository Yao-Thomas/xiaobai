"""
export_quantized.py —— 任务 C/F 的交付物导出：quantized_model/

★ 严格按 07_接口约定单.md 接口 ① 的目录结构：
    quantized_model/
    ├─ weights.bin           int8 权重（每层 128B 对齐）
    ├─ model_spec.json       模型结构描述
    ├─ reference_in.bin      ★ 测试输入（N 个 int8 图像，连续存放）
    ├─ reference_out.bin     ★ CPU 参考输出（与硬件逐位一致的整数复刻）
    └─ README.md             内存布局图 / 怎么用 / 注意事项

★ 自检（导出脚本末尾强制跑，不通过就报错退出）：
    重新从 weights.bin + reference_in.bin 读回 → 跑 numpy 硬件复刻 →
    与 reference_out.bin 逐点比对，必须 100% 相同。
    这正是板子侧集成时用的同一套判据（"喂同样的输入，看输出是否逐点一致"）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np
import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "common"))

from qmodel import QWaveNet, reference_infer_arrays, IMG                # noqa: E402

CLASSES = ["sine", "square", "triangle", "sawtooth", "noise",
           "glitch", "clipping", "signal_loss", "duty_abnormal"]

ALIGN = 128          # 每层起始地址对齐到 128 字节（接口约定要求说明对齐）
PAD_MULT = 64        # 文件尾部补齐到 64 的倍数（★ 上一轮 cache line 坑）


def align_up(x, a):
    return (x + a - 1) // a * a


def build_weight_blob(w1, w2, wf, align=ALIGN, pad_mult=PAD_MULT):
    """按 DDR 布局拼 weights.bin，返回 (blob, layout)
       布局顺序：Conv1 → Conv2 → FC（接口约定建议的顺序）"""
    import io
    parts = []
    layout = []
    off = 0

    def put(name, arr, shape, desc):
        nonlocal off
        b = arr.astype(np.int8).tobytes()
        start = off
        parts.append(b)
        off += len(b)
        # 补齐到 64 的倍数，再对齐到 align
        nb = align_up(off, pad_mult)
        if nb > off:
            parts.append(b"\x00" * (nb - off)); off = nb
        nb2 = align_up(off, align)
        if nb2 > off:
            parts.append(b"\x00" * (nb2 - off)); off = nb2
        layout.append({"name": name, "offset": start, "bytes": len(b),
                       "shape": shape, "desc": desc})

    put("conv1.weight", w1, [8, 1, 3, 3], "Conv1 权重 [out_ch=8][in_ch=1][3][3]")
    put("conv2.weight", w2, [16, 8, 3, 3], "Conv2 权重 [out_ch=16][in_ch=8][3][3]")
    put("fc.weight", wf, [wf.shape[0], wf.shape[1]], "FC 权重 [out=N][in=400]")
    blob = b"".join(parts)
    return blob, layout


def class_balanced_indices(labels, per_class):
    idx = []
    for c in range(len(CLASSES)):
        w = np.where(labels == c)[0]
        if len(w) >= per_class:
            idx += list(w[:: max(1, len(w) // per_class)][:per_class])
        else:
            idx += list(w)
    return np.asarray(sorted(idx), dtype=np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="train 输出目录（含 model_final.pt）")
    ap.add_argument("--data", required=True, help="dataset 目录")
    ap.add_argument("--out", required=True, help="输出 quantized_model/ 目录")
    ap.add_argument("--per-class", type=int, default=8, help="参考样本每类条数")
    ap.add_argument("--uniform-mfq", type=int, default=0,
                    help=">0：额外导出一个「全层同一 MFQ」的兼容版本")
    ap.add_argument("--split", default="test")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # ★ 输入表示 / 预处理参数 / 类别表都必须来自数据集本身
    #   （数据集是契约的权威来源），绝不能在这里写死 ——
    #   否则 model_spec.json 会与训练时用的东西不一致。
    ds_meta = {}
    meta_path = os.path.join(args.data, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            ds_meta = json.load(f)
    global CLASSES                       # 必须在使用 CLASSES 之前声明
    if ds_meta.get("classes"):
        CLASSES = list(ds_meta["classes"])
    input_type = ds_meta.get("input_type", "wdens")
    pp_params = ds_meta.get("pp_params", {})
    dataset_version = ds_meta.get("dataset_version")
    dataset_source = ds_meta.get("source")
    ds_excluded = ds_meta.get("excluded_classes")

    model = QWaveNet(n_classes=len(CLASSES))
    sd = torch.load(os.path.join(args.model, "model_final.pt"), map_location="cpu")
    model.load_state_dict(sd)
    model.eval()
    for m in (model.conv1, model.conv2, model.fc):
        m.warm = False

    iw = model.int_weights()
    w1 = iw["conv1.weight"].numpy().astype(np.int8)
    w2 = iw["conv2.weight"].numpy().astype(np.int8)
    wf = iw["fc.weight"].numpy().astype(np.int8)
    mfq = model.mfq_list()

    # ---- 测试集评估（用 numpy 硬件复刻，与硬件逐位一致）----
    packed = os.path.join(args.data, "packed")
    xte = np.load(os.path.join(packed, "img_%s.npy" % args.split))
    yte = np.load(os.path.join(packed, "label_%s.npy" % args.split))

    preds = np.empty(len(xte), dtype=np.int64)
    for i in range(len(xte)):
        lg, _, _ = reference_infer_arrays(xte[i], w1, w2, wf, mfq)
        preds[i] = int(np.argmax(lg))
    acc = float((preds == yte).mean())

    # 训练报告里的【浮点路径】精度 —— 这才是"量化损失"的对照基准
    tr_json = os.path.join(args.model, "train_report.json")
    base_acc = None
    if os.path.exists(tr_json):
        with open(tr_json, encoding="utf-8") as f:
            rep = json.load(f)
        # ★ 第一版这里取的是 test_acc_torch（整数前向自己的准确率），
        #   于是报告里的"量化损失"恒等于 0 —— 是个假结论。必须是浮点路径的准确率。
        base_acc = rep.get("final", {}).get("test_acc_float")

    # ---- weights.bin ----
    blob, layout = build_weight_blob(w1, w2, wf)
    with open(os.path.join(args.out, "weights.bin"), "wb") as f:
        f.write(blob)

    # ---- reference_in / reference_out ----
    sel = class_balanced_indices(yte, args.per_class)
    ref_in_u8 = xte[sel]                                     # (N,1,28,28) uint8
    ref_in_i8 = (ref_in_u8.astype(np.int16) - 128).astype(np.int8)
    ref_out = np.stack([reference_infer_arrays(ref_in_u8[i], w1, w2, wf, mfq)[0]
                        for i in range(len(sel))]).astype(np.int8)
    ref_lab = yte[sel].astype(np.int64)

    with open(os.path.join(args.out, "reference_in.bin"), "wb") as f:
        f.write(ref_in_i8.tobytes())
    with open(os.path.join(args.out, "reference_out.bin"), "wb") as f:
        f.write(ref_out.tobytes())

    # ---- 统一 MFQ 兼容版（可选）----
    uniform_note = None
    if args.uniform_mfq and args.uniform_mfq > 0:
        um = int(args.uniform_mfq)
        pu = np.empty(len(xte), dtype=np.int64)
        for i in range(len(xte)):
            lg, _, _ = reference_infer_arrays(xte[i], w1, w2, wf, [um, um, um])
            pu[i] = int(np.argmax(lg))
        uniform_note = {"MFQ": um, "test_acc": float((pu == yte).mean()),
                        "matches_per_layer_acc": bool(np.array_equal(pu, preds))}
        uo = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                          os.path.basename(args.out.rstrip("/")) + "_uniform_mfq")
        os.makedirs(uo, exist_ok=True)
        shutil.copy(os.path.join(args.out, "weights.bin"), os.path.join(uo, "weights.bin"))
        with open(os.path.join(uo, "reference_in.bin"), "wb") as f:
            f.write(ref_in_i8.tobytes())
        with open(os.path.join(uo, "reference_out.bin"), "wb") as f:
            f.write(ref_out.tobytes())
    # ---- model_spec.json ----
    spec = {
        "model_name": "wavenet9_28x28",
        "task": "scope_waveform_recognition",
        "input_shape": [1, IMG, IMG],
        "input_type": input_type,
        "input_dtype": "int8",
        "input_quant": {
            "note": "★ 唯一输入变换：int8 = uint8 - 128（8 位 ADC 码值中心化），scale = 1.0",
            "u8_to_i8": "i8 = clip(u8 - 128, -128, 127)",
            "preprocess": {"mode": input_type, **pp_params},
            "dataset": {"version": dataset_version, "source": dataset_source},
            "impl": "src/common/preprocess.py（numpy 与纯 Python 两条路径逐点一致）",
        },
        "layers": [
            {"type": "conv", "name": "conv1", "in_ch": 1, "out_ch": 8, "k": 3,
             "stride": 1, "pad": 0, "out_hw": [13, 13],
             "note": "该层与 2x2 max-pool 融合（同 HLS cnn_conv_pool_q，池化步长 P=2）"},
            {"type": "relu"},
            {"type": "pool", "k": 2, "stride": 2},
            {"type": "conv", "name": "conv2", "in_ch": 8, "out_ch": 16, "k": 3,
             "stride": 1, "pad": 0, "out_hw": [5, 5],
             "note": "同上，与 2x2 max-pool 融合"},
            {"type": "relu"},
            {"type": "pool", "k": 2, "stride": 2},
            {"type": "fc", "name": "fc", "in": 400, "out": len(CLASSES)},
        ],
        "requant": {
            "formula": "out = relu/sat((acc * MFQ) >> 16)",
            "shift": 16,
            "MFQ": int(mfq[2]),
            "MFQ_per_layer": {"conv1": int(mfq[0]), "conv2": int(mfq[1]), "fc": int(mfq[2])},
            "MFQ_note": (
                "★ MFQ 是 HLS 的 s_axilite 寄存器（每次调用独立传入），不是硬件常量。"
                "上一轮 MNIST 模型的校准值 119 不适用于本模型。"
                "ps 侧按 conv1→conv2→fc 顺序依次写 MFQ_per_layer；"
                "若板端只支持单一 MFQ，请使用 quantized_model_uniform_mfq/ 版本。"),
            "bias": "无偏置（与 HLS 一致，不传 bias 数组）",
            "overflow_rule": "HLS 内 acc*MFQ 为 ap_int<32>，本项目已保证 max|acc|*MFQ < 2^31",
        },
        "accuracy": {
            "test_set": acc,
            "test_set_float_baseline": base_acc,
            "quantization_loss": (None if base_acc is None else float(base_acc - acc)),
            "n_test": int(len(xte)),
            "notes": "test_acc 用 numpy 硬件复刻整数前向测得（与 PL 逐位一致）",
        },
        "classes": CLASSES,
        "classes_note": (
            None if not ds_excluded else
            "★ 本模型不含类别 %s。理由（已实测，见 docs/01_输入表示选型.md §4）："
            "毛刺只有 2~10 个采样点，映射到 28×28 密度图后只改变 2~5 / 784 个像素，"
            "在同样的表示上做二分类只能收敛到多数类（召回 0.000），"
            "即**在 4096 点采集 + 28×28 画布上不可分**。"
            "按 06_分工总表 的分工，毛刺由**示波器负责人的 PL 硬件故障检测器**"
            "（100 MHz / 10 ns 分辨率）负责。需要 9 类时用 "
            "`dataset_gen.py --with-glitch` 重新生成数据集即可，代码路径完全一致。"
            % ", ".join(ds_excluded)),
        "class_descriptions": {
            "sine": "正弦", "square": "方波", "triangle": "三角波",
            "sawtooth": "锯齿波", "noise": "噪声/无周期信号",
            "glitch": "毛刺（窄脉冲）", "clipping": "削顶（含轻度削顶）",
            "signal_loss": "丢信号（平线或强衰减）", "duty_abnormal": "占空比异常",
        },
        "weights_layout": {
            "file": "weights.bin",
            "dtype": "int8", "endianness": "小端（单字节无所谓）",
            "align_bytes": ALIGN, "tail_pad_multiple": PAD_MULT,
            "total_bytes": len(blob),
            "order": [l["name"] for l in layout],
            "entries": layout,
            "index_order": {
                "conv": "w[(oc*IN_CH + ic)*KH*KW + ky*KW + kx]   ← 与 HLS 完全一致",
                "fc": "w[oc*IN + i]",
            },
        },
        "buffers": {
            "note": "加速器按层读写 DDR 的缓冲区尺寸（★ 全部 64 字节对齐并补齐到 64 的倍数，"
                    "上一轮就是因为最后一条不完整 cache line 未失效导致尾部全 0）",
            "input_img": {"bytes": IMG * IMG, "padded": align_up(IMG * IMG, PAD_MULT)},
            "conv1_out_f1": {"shape": [8, 13, 13], "bytes": 8 * 13 * 13,
                             "padded": align_up(8 * 13 * 13, PAD_MULT)},
            "conv2_out_f2": {"shape": [16, 5, 5], "bytes": 16 * 5 * 5,
                             "padded": align_up(16 * 5 * 5, PAD_MULT)},
            "logits": {"shape": [len(CLASSES)], "bytes": len(CLASSES),
                       "padded": align_up(len(CLASSES), PAD_MULT)},
        },
        "reference": {
            "n_samples": int(len(sel)),
            "labels": [CLASSES[int(v)] for v in ref_lab],
            "reference_in_format": "连续的 int8 图像，每个 %d 字节（= 28*28），"
                                   "即加速器输入缓冲的直接内容" % (IMG * IMG),
            "reference_out_format": "连续的 int8 logits，每个 %d 字节，顺序与输入一致"
                                    % len(CLASSES),
            "how_to_compare": "对第 k 个输入跑一遍硬件，把 %d 字节输出与 "
                              "reference_out.bin[k*%d:(k+1)*%d] 逐点比对，"
                              "应全部相同（对应上一轮的 [CNN OK] N/N 点一致）"
                              % (len(CLASSES), len(CLASSES), len(CLASSES)),
        },
        "generated_by": "src/train/export_quantized.py",
    }
    if uniform_note:
        spec["requant"]["uniform_mfq_variant"] = uniform_note
    with open(os.path.join(args.out, "model_spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    # ★ 统一 MFQ 兼容版必须自带 model_spec.json + README.md，而且要写【它自己的】准确率
    #   （曾经直接把逐层版的 spec 拷过去，accuracy 显示 0.959，是错的 —— 那版的真实值是 0.554）
    if uniform_note:
        uspec = json.loads(json.dumps(spec, ensure_ascii=False))
        uspec["model_name"] = spec["model_name"] + "_uniform_mfq"
        uspec["uniform_mfq_variant"] = True
        uspec["requant"]["MFQ"] = uniform_note["MFQ"]
        uspec["requant"]["MFQ_per_layer"] = {k: uniform_note["MFQ"]
                                             for k in ("conv1", "conv2", "fc")}
        uspec["requant"]["MFQ_note"] = (
            "★ 兼容回退版：全网络统一 MFQ=%d（板端只需写一个寄存器值）。"
            "准确率明显低于逐层版 —— 因为 conv1 只有 9 次累加、FC 有 400 次，"
            "acc 峰值差 40 倍以上，统一乘子必然让某些层的权重被压到只剩 1~2 个量化级。"
            % uniform_note["MFQ"])
        uspec["accuracy"]["test_set"] = uniform_note["test_acc"]
        uspec["accuracy"]["per_layer_variant_test_set"] = acc
        uspec["accuracy"]["notes"] = (
            "★ 本目录是统一 MFQ 回退版，test_set 是【该版】实测准确率；"
            "逐层版的准确率 %.4f。除非板端 PS 代码确实只能传一个 MFQ，"
            "否则请用逐层版 ../%s/。" % (acc, os.path.basename(args.out.rstrip("/"))))
        with open(os.path.join(uo, "model_spec.json"), "w", encoding="utf-8") as f:
            json.dump(uspec, f, ensure_ascii=False, indent=2)
        if os.path.exists(os.path.join(args.out, "README.md")):
            shutil.copy(os.path.join(args.out, "README.md"),
                        os.path.join(uo, "README.md"))
            with open(os.path.join(uo, "README.md"), "a", encoding="utf-8") as f:
                f.write("\n\n---\n\n## ★ 本目录是【统一 MFQ 兼容回退版】\n\n")
                f.write("全部层使用 **MFQ = %d**（板端只需写一个寄存器值）。\n\n"
                        % uniform_note["MFQ"])
                f.write("**该版实测测试集准确率：%.4f**；逐层版为 **%.4f**。\n\n"
                        % (uniform_note["test_acc"], acc))
                f.write("除非板端 PS 代码确实只能传一个 MFQ，"
                        "**否则请用 `../%s/`（逐层版）**。\n"
                        % os.path.basename(args.out.rstrip("/")))

    # ---- C 数组（方便裸机/PS 直接 include）----
    with open(os.path.join(args.out, "weights.h"), "w", encoding="utf-8") as f:
        f.write("/* 自动生成：int8 权重 + 布局常量（与 weights.bin 完全一致） */\n")
        f.write("#ifndef WAVENET_WEIGHTS_H\n#define WAVENET_WEIGHTS_H\n")
        f.write("#define WN_CONV1_OFF 0x%04X\n#define WN_CONV2_OFF 0x%04X\n"
                "#define WN_FC_OFF    0x%04X\n#define WN_TOTAL     %d\n"
                % (layout[0]["offset"], layout[1]["offset"], layout[2]["offset"], len(blob)))
        f.write("#define WN_MFQ_CONV1 %d\n#define WN_MFQ_CONV2 %d\n#define WN_MFQ_FC %d\n"
                % (mfq[0], mfq[1], mfq[2]))
        b = np.frombuffer(blob, dtype=np.uint8)
        f.write("static const unsigned char wavenet_weights[%d] = {\n" % len(b))
        for i in range(0, len(b), 16):
            f.write("  " + ",".join("0x%02X" % v for v in b[i:i + 16]) + ",\n")
        f.write("};\n#endif\n")

    # ---- README.md ----
    lines = []
    A = lines.append
    A("# quantized_model —— 波形识别模型② 交付包\n")
    A("> 项目：系统管家小白（Zynq-7020）· 生成者：AI 训练负责人")
    A("> 格式依据：`07_接口约定单.md` 接口 ①（★ 未单方面改动任何必需字段）\n")
    A("## 1. 这是什么\n")
    A("一个 **1×28×28 int8 输入 / %d 类输出** 的小 CNN，与上一轮 PL 侧 CNN 加速器" % len(CLASSES))
    A("（`cnn_conv_pool_q` + `cnn_fc_q`）**逐位同构**：把它接上既有 IP 就应当直接跑通。\n")
    A("类别（输出下标顺序）：`%s`\n" % "`, `".join(CLASSES))
    A("## 2. 文件清单\n")
    A("| 文件 | 说明 |")
    A("|---|---|")
    A("| `weights.bin` | int8 权重，%d 字节（布局见 §4） |" % len(blob))
    A("| `model_spec.json` | 模型结构 + requant 参数 + 内存布局 + 精度 |")
    A("| `reference_in.bin` | ★ %d 组测试输入，每组 %d 字节 int8 |" % (len(sel), IMG * IMG))
    A("| `reference_out.bin` | ★ 对应的 %d 组输出，每组 %d 字节 int8（与硬件逐位一致） |"
      % (len(sel), len(CLASSES)))
    A("| `weights.h` | 同一份权重的 C 数组（方便裸机直接 include） |")
    A("| `README.md` | 本文件 |\n")
    A("## 3. ★ 怎么验证（板子侧唯一可靠的做法）\n")
    A("```")
    A("for k in 0 .. %d:" % (len(sel) - 1))
    A("    把 reference_in.bin[k*%d : (k+1)*%d] 拷进加速器输入缓冲（DDR，64B 对齐）"
      % (IMG * IMG, IMG * IMG))
    A("    依次驱动 Conv1 → Conv2 → FC")
    A("    读回 %d 字节 logits" % len(CLASSES))
    A("    与 reference_out.bin[k*%d : (k+1)*%d] 逐点比对 → 应 100%% 相同"
      % (len(CLASSES), len(CLASSES)))
    A("```")
    A("期望输出形如上一轮的 `[CNN OK] %d/%d 点一致`。\n" % (len(CLASSES), len(CLASSES)))
    A("参考样本的类别顺序（方便人工核对）：\n")
    A("```")
    A(", ".join(CLASSES[int(v)] for v in ref_lab))
    A("```\n")
    A("## 4. ★ DDR 内存布局（weights.bin）\n")
    A("```")
    for l in layout:
        A("偏移 0x%04X: %-14s shape %-14s %5d 字节"
          % (l["offset"], l["name"], str(l["shape"]), l["bytes"]))
    A("文件总长          %-29s %5d 字节" % ("", len(blob)))
    A("```\n")
    A("| 偏移 | 层 | 形状 | 字节 | 说明 |")
    A("|---|---|---|---|---|")
    for l in layout:
        A("| `0x%04X` | %s | %s | %d | %s |"
          % (l["offset"], l["name"], l["shape"], l["bytes"], l["desc"]))
    A("")
    A("- 每层起始地址 **对齐到 %d 字节**；层间与文件尾**补齐到 %d 的倍数**（cache line 安全）"
      % (ALIGN, PAD_MULT))
    A("- 索引顺序（★ 与 HLS 源码完全一致）：")
    A("  - conv: `w[(oc*IN_CH + ic)*KH*KW + ky*KW + kx]`")
    A("  - fc  : `w[oc*IN + i]`")
    A("- **无偏置**（HLS 不读 bias 数组，网络按 `bias=False` 训练）")
    A("- 文件总大小：**%d 字节**\n" % len(blob))
    A("## 5. 各层缓冲区尺寸（DDR）\n")
    A("| 缓冲 | 形状 | 字节 | 建议对齐/补齐 |")
    A("|---|---|---|---|")
    for k, v in spec["buffers"].items():
        if k == "note":
            continue
        A("| %s | %s | %s | %s |" % (k, v.get("shape", "-"), v.get("bytes", "-"),
                                     v.get("padded", "-")))
    A("")
    A("> ★ 上一轮的坑：输出缓冲**最后一条不完整 cache line 未失效**会让板端结果尾部全 0。")
    A("> 所有缓冲请 64 字节对齐 + 长度补齐到 64 的倍数（上面已给出 padded 值）。\n")
    A("## 6. requant（★ 沿用上一轮方案，硬件零改动）\n")
    A("```")
    A("out = relu/sat((acc * MFQ) >> 16)      # conv: relu+sat 到 [0,127]")
    A("                                        # fc  : sat 到 [-128,127]（无 ReLU）")
    A("```")
    A("| 层 | MFQ |")
    A("|---|---|")
    A("| conv1 | %d |" % mfq[0])
    A("| conv2 | %d |" % mfq[1])
    A("| fc | %d |" % mfq[2])
    A("")
    A("**★ 为什么要说明这一点：**")
    A("`MFQ` 在 HLS 里是 `s_axilite` 寄存器（`cnn_conv_pool_q(..., int MFQ)`），")
    A("**每次调用独立传入，不是硬件常量**。上一轮的 `MFQ=119` 是那个 MNIST 模型的")
    A("主机校准值；本模型是另一个网络、另一种输入分布，必须重新校准。")
    A("方案本身（`(acc×MFQ)>>16` + 主机校准）完全沿用，PL 侧一行都不用改。")
    if uniform_note:
        A("")
        A("**兼容回退**：若板端只支持「整个网络用一个 MFQ」，请用同一目录旁的")
        A("`%s_uniform_mfq/`，那里 MFQ 统一为 **%d**（测试集准确率 %.4f，原逐层版 %.4f）。"
          % (os.path.basename(args.out.rstrip("/")), uniform_note["MFQ"],
             uniform_note["test_acc"], acc))
    A("")
    A("## 7. 输入预处理（capture → 28×28）\n")
    A("示波器 4096 个 8 位样本 → 28×28 uint8 图像 → `int8 = u8 - 128`。\n")
    if input_type == "wdens":
        A("**本模型使用的输入表示：`wdens`（时间×幅度密度图）**")
        A("```")
        A(" 28 列 = 时间（把 4096 个采样点均分成 28 段，每段 146 点）")
        A(" 28 行 = 幅度（8 位码值 0~255 均分；行 0 = 顶部 = 高电平）")
        A(" 每个格子的值 = 该列内落在该幅度档的采样点【个数】")
        A("   → 除以该列总点数得到列内密度 → 开平方（方差稳定化）")
        A("   → 按【本样本自身最大值】归一化到 0~255")
        A("```")
        A("为什么不用 STFT：STFT 要分开谐波需要「一个窗内至少 2 个周期」，")
        A("而示波器为显示 2~5 个周期时缓冲区内只有 K=2~5 个周期 ⇒ 谐波完全糊在一起。")
        A("密度图在少周期时直接给出波形形状，多周期时退化为各列的幅度分布")
        A("（正弦=反正弦分布 / 三角=均匀 / 方波=双尖峰 / 噪声=高斯），两个工况下都有判别力。")
        A("**实测对比见 `docs/01_输入表示选型.md`。**")
    else:
        A("**本模型使用的输入表示：`stft`（对数频率时频图）**")
        A("参数：`NFFT=512, hop=132, Hann 窗, 28 帧, 对数频率轴(bin 1..256 → 28 行), ")
        A("相对峰值固定 60 dB 动态范围`。")
    A("")
    A("**参考实现：`src/common/preprocess.py`（含 numpy 与纯 Python 两条路径，逐点一致）。**")
    A("板端若要用，直接拷这个文件即可（无第三方依赖）。\n")
    A("## 8. 精度\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 测试集准确率（整数前向，与硬件一致） | **%.4f** |" % acc)
    if base_acc is not None:
        A("| 浮点基线（量化前） | %.4f |" % base_acc)
        A("| 量化损失 | %.4f（目标 < 0.02） |" % (base_acc - acc))
    A("| 测试集规模 | %d |" % len(xte))
    A("")
    A("## 9. 注意事项\n")
    A("- 输入必须是 **int8**，值为 `uint8-128`；不要送原始 0~255。")
    A("- 每层权重起始地址必须按 §4 的表；不要重新排列层顺序。")
    A("- 中间特征图 f1/f2 直接由加速器写 DDR 并被下一层读回，")
    A("  **CPU 侧不要对它们做 flush**（上一轮的坑：会把旧值刷回去覆盖加速器结果）。")
    A("- 所有缓冲区按 §5 的 padded 尺寸分配。")
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # ================= ★ 强制自检 =================
    print("=== 自检：从导出文件重新读回并逐点比对 ===")
    blob2 = np.fromfile(os.path.join(args.out, "weights.bin"), dtype=np.uint8)
    assert len(blob2) == len(blob), "weights.bin 长度不符"
    rw1 = blob2[layout[0]["offset"]:layout[0]["offset"] + 72].astype(np.int8).reshape(8, 1, 3, 3)
    rw2 = blob2[layout[1]["offset"]:layout[1]["offset"] + 1152].astype(np.int8).reshape(16, 8, 3, 3)
    rw3 = blob2[layout[2]["offset"]:layout[2]["offset"] + wf.size].astype(np.int8).reshape(wf.shape)
    assert np.array_equal(rw1, w1), "conv1 读回不一致"
    assert np.array_equal(rw2, w2), "conv2 读回不一致"
    assert np.array_equal(rw3, wf), "fc 读回不一致"

    rin = np.fromfile(os.path.join(args.out, "reference_in.bin"), dtype=np.int8)
    rout = np.fromfile(os.path.join(args.out, "reference_out.bin"), dtype=np.int8)
    N = len(sel)
    assert len(rin) == N * IMG * IMG, "reference_in.bin 长度 %d != %d" % (len(rin), N * IMG * IMG)
    assert len(rout) == N * len(CLASSES), "reference_out.bin 长度不符"

    ok_pts, tot_pts = 0, 0
    for k in range(N):
        # ★ reference_in.bin 存的是【加速器输入】= int8 = uint8 - 128。
        #   而参考实现 reference_infer_arrays 的入参是 uint8 码值，
        #   所以这里必须先 +128 还原（第一版漏了这一步，导致自检假失败）。
        img_i8 = rin[k * IMG * IMG:(k + 1) * IMG * IMG].reshape(IMG, IMG)
        img_u8 = (img_i8.astype(np.int16) + 128).astype(np.uint8)
        lg, _, _ = reference_infer_arrays(img_u8, rw1, rw2, rw3, mfq)
        exp = rout[k * len(CLASSES):(k + 1) * len(CLASSES)]
        same = int((lg.astype(np.int8) == exp).sum())
        ok_pts += same
        tot_pts += len(CLASSES)
        if same != len(CLASSES):
            print("  [MISMATCH] sample %d: %s vs %s" % (k, lg.tolist(), exp.tolist()))
    print("  [EXPORT OK] %d/%d 点一致（%d 组参考样本）" % (ok_pts, tot_pts, N))
    assert ok_pts == tot_pts, "★ 导出自检失败：reference_out.bin 与读回权重不自洽"

    # ★ 再独立验一次 argmax：从 reference_in.bin 直接算出的预测 必须等于
    #   reference_out.bin 每行 argmax —— 板子侧真正关心的就是这个。
    pred_from_files = np.array([
        int(np.argmax(reference_infer_arrays(
            (rin[k * IMG * IMG:(k + 1) * IMG * IMG].astype(np.int16) + 128).astype(np.uint8),
            rw1, rw2, rw3, mfq)[0]))
        for k in range(N)])
    pred_ref = np.argmax(rout.reshape(N, -1), axis=1)
    assert np.array_equal(pred_from_files, pred_ref), "★ reference_out.bin 的 argmax 不自洽"
    print("  [EXPORT OK] argmax 自洽 %d/%d" % (int((pred_from_files == pred_ref).sum()), N))

    print("  weights.bin    : %d bytes (layout ok, %d-byte align)" % (len(blob), ALIGN))
    print("  reference_in   : %d samples x %d B" % (N, IMG * IMG))
    print("  reference_out  : %d samples x %d B" % (N, len(CLASSES)))
    print("  test_acc       : %.4f" % acc)
    if base_acc is not None:
        print("  float baseline : %.4f  (量化损失 %.4f)" % (base_acc, base_acc - acc))
    if uniform_note:
        print("  uniform MFQ=%d : test_acc %.4f" % (uniform_note["MFQ"], uniform_note["test_acc"]))
    print("输出目录 ->", args.out)


if __name__ == "__main__":
    main()
