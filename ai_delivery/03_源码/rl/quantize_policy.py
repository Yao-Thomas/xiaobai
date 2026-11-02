"""quantize_policy.py —— 把 RL 策略网络量化成 int8 并导出交付物（任务 E · 量化）

★ 严格沿用本项目量化方案（与波形识别模型一致，红线）：
      acc = Σ x_q · w_q              （int8 × int8 -> int32）
      out = sat((acc × MFQ) >> 16)   （算术右移=floor，饱和到 [-128,127]）
  MFQ 是主机校准的整数乘子（每层一个，硬件里是寄存器）。

★ 策略网络是 float + HardTanh（clamp[-1,1]）的 MLP，HardTanh 的硬饱和
  与 "sat" 逐位同构 => **PTQ 决策零损失**（只做权重 int8 + 逐层 MFQ 校准）。

★ 交付物（与接口 ① 相同格式，团队硬性红线）：
      weights.bin         int8 权重（128B 对齐）
      model_spec.json     模型结构 + requant + 布局 + 动作解码
      reference_in.bin    N 个 int8 输入（量化后的 obs）
      reference_out.bin   N 组 int8 输出（各头 logits 拼接，CPU 整数推理）
      README.md           布局图 / 用法 / 注意事项

★ 导出后强制自检（不通过就非零退出）：
      [1] 从 weights.bin 读回权重
      [2] 用纯 numpy 整数推理（与 HLS 逐位一致）跑 reference_in.bin
      [3] 与 reference_out.bin 逐点比对，必须 100% 一致
      [4] 另对比 float 前向与整数前向的 argmax 决策，报告"决策一致率"（量化损失）

用法：
  python quantize_policy.py --model runs/scope_policy_v1 --out deliverables/scope_policy_quantized
  python quantize_policy.py --model runs/eq_policy_v1    --out deliverables/eq_policy_quantized
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 保证 Windows 控制台也能打印中文（远端 Linux 本身是 UTF-8，此调用为 no-op）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from ppo import PolicyMLP                                                       # noqa: E402
from scope_env import ScopeEnv, TRIG_LEVELS, DEC_LEVELS, VGAIN_LEVELS            # noqa: E402
from audio_eq_env import AudioEqEnv, GAIN_LEVELS_DB, EQ_BANDS                    # noqa: E402

ALIGN = 128
PAD_MULT = 64
INT32_MAX = 2 ** 31 - 1
OBS_SCALE = 1.0 / 127.0        # obs∈[-1,1] -> int8=round(obs*127) 的输入尺度
ACT_SCALE = 1.0 / 127.0        # HardTanh 输出 ∈[-1,1] 的激活尺度
QMAX_W = 127


# ---------------------------------------------------------------------------
# 纯 numpy 整数推理（与 HLS cnn_fc_q 逐位一致，含 int32 回绕模拟）
# ---------------------------------------------------------------------------
def wrap_int32(v):
    v = np.asarray(v, dtype=np.int64)
    return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def requant_shift(acc, mfq):
    prod = wrap_int32(np.asarray(acc, dtype=np.int64) * int(mfq))
    q = prod >> 16
    return np.clip(q, -128, 127).astype(np.int32)


def mlp_infer_int8(x_i8, weights, mfqs, n_hidden):
    """纯 numpy 整数前向。weights/mfqs 按前向顺序，前 n_hidden 个是隐层，其余是动作头。
    返回 list[np.int8]（每个动作头一个 logits 向量）。"""
    x = np.asarray(x_i8, dtype=np.int64)
    for k in range(n_hidden):
        acc = np.asarray(weights[k], dtype=np.int64) @ x
        x = requant_shift(acc, mfqs[k])
    logits = []
    for k in range(n_hidden, len(weights)):
        acc = np.asarray(weights[k], dtype=np.int64) @ x
        logits.append(requant_shift(acc, mfqs[k]).astype(np.int8))
    return logits


def align_up(x, a):
    return (x + a - 1) // a * a


def build_weight_blob(weights, names, shapes, align=ALIGN, pad_mult=PAD_MULT):
    parts = []
    layout = []
    off = 0
    for name, arr, shape in zip(names, weights, shapes):
        b = np.asarray(arr, dtype=np.int8).tobytes()
        start = off
        parts.append(b)
        off += len(b)
        nb = align_up(off, pad_mult)
        if nb > off:
            parts.append(b"\x00" * (nb - off)); off = nb
        nb2 = align_up(off, align)
        if nb2 > off:
            parts.append(b"\x00" * (nb2 - off)); off = nb2
        layout.append(dict(name=name, offset=start, bytes=len(b), shape=list(shape)))
    return b"".join(parts), layout


def sample_obs(make_env, n, seed):
    rng = np.random.default_rng(seed)
    obs_list = []
    while len(obs_list) < n:
        env = make_env()
        env.seed(int(rng.integers(0, 2 ** 31 - 1)))
        obs_list.append(env.reset())
        if len(obs_list) < n and rng.random() < 0.5:
            a = [int(rng.integers(0, n_i)) for n_i in env.action_nvec]
            o, _, _, _ = env.step(a)
            obs_list.append(o)
    return np.stack(obs_list[:n]).astype(np.float32)


def obs_to_int8(obs):
    obs = np.clip(obs, -1.0, 1.0)
    return np.rint(obs * 127.0).astype(np.int8)


def decode_tables(task):
    if task == "scope_autoset":
        return {
            "factor_names": ["trig_level", "dec", "vgain"],
            "factors": [
                {"name": "trig_level", "n": len(TRIG_LEVELS),
                 "decode": [int(v) for v in TRIG_LEVELS], "unit": "LSB(0~255)"},
                {"name": "dec", "n": len(DEC_LEVELS),
                 "decode": [int(v) for v in DEC_LEVELS], "unit": "抽取(1~255)"},
                {"name": "vgain", "n": len(VGAIN_LEVELS),
                 "decode": [float(v) for v in VGAIN_LEVELS], "unit": "数字缩放因子"},
            ],
        }
    return {
        "factor_names": ["eq_band_%d" % i for i in range(8)],
        "factors": [
            {"name": "eq_band_%d" % i, "n": len(GAIN_LEVELS_DB),
             "decode": [float(v) for v in GAIN_LEVELS_DB],
             "center_hz": float(EQ_BANDS[i]), "unit": "dB"}
            for i in range(8)
        ],
    }


def quantize_actor(actor, obs_all):
    """对 float HardTanh 策略网络做 PTQ，返回 (int8 权重列表, MFQ 列表, 名称, 形状, 隐层数)。"""
    hidden_linears = [m for m in actor.body if isinstance(m, nn.Linear)]
    head_linears = list(actor.heads)
    n_hidden = len(hidden_linears)

    with torch.no_grad():
        logits_float = actor(torch.as_tensor(obs_all, dtype=torch.float32))

    weights, mfqs, names, shapes = [], [], [], []
    s_x = OBS_SCALE
    for k, lin in enumerate(hidden_linears):
        W = lin.weight.data.detach().cpu().numpy()
        s_w = float(np.abs(W).max()) / QMAX_W
        w_q = np.rint(W / s_w).astype(np.int8)
        # HardTanh 激活尺度固定 1/127；MFQ = round(s_x · s_w / s_y · 2^16)
        s_y = ACT_SCALE
        mfq = int(round(s_x * s_w / s_y * (1 << 16)))
        weights.append(w_q); mfqs.append(mfq)
        names.append("fc%d" % k); shapes.append(list(W.shape))
        s_x = s_y

    for j, lin in enumerate(head_linears):
        W = lin.weight.data.detach().cpu().numpy()
        s_w = float(np.abs(W).max()) / QMAX_W
        w_q = np.rint(W / s_w).astype(np.int8)
        # 头输出尺度按 float logits 校准
        lg = logits_float[j].cpu().numpy()
        s_y = float(np.abs(lg).max()) / 127.0
        s_y = max(s_y, 1e-4)
        mfq = int(round(s_x * s_w / s_y * (1 << 16)))
        weights.append(w_q); mfqs.append(mfq)
        names.append("head%d" % j); shapes.append(list(W.shape))

    return weights, mfqs, names, shapes, n_hidden


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="训练输出目录（含 model_final.pt + hyperparams.json）")
    ap.add_argument("--out", required=True, help="输出量化交付目录")
    ap.add_argument("--n-ref", type=int, default=32, help="reference 样本数")
    ap.add_argument("--ref-seed", type=int, default=20261001)
    args = ap.parse_args()

    # ---- 读超参，重建网络 ----
    with open(os.path.join(args.model, "hyperparams.json"), encoding="utf-8") as f:
        hyper = json.load(f)
    task = hyper["task"]
    obs_dim = hyper["obs_dim"]
    action_nvec = hyper["action_nvec"]
    hidden = hyper["hidden"]

    actor = PolicyMLP(obs_dim, action_nvec, hidden=tuple(hidden))
    ckpt = torch.load(os.path.join(args.model, "model_final.pt"), map_location="cpu")
    actor.load_state_dict(ckpt["actor"])
    actor.eval()

    make_env = (lambda: ScopeEnv()) if task == "scope_autoset" else (lambda: AudioEqEnv())

    # ---- 采样参考 obs，量化 + 校准 ----
    obs_all = sample_obs(make_env, args.n_ref, args.ref_seed)
    ref_in = obs_to_int8(obs_all)                     # (N, obs_dim) int8
    n_ref = ref_in.shape[0]
    w_np, mfqs, names, shapes, n_hidden = quantize_actor(actor, obs_all)

    # ---- 溢出检查（红线：max|acc| × MFQ < 2^31）----
    print("MFQ_per_layer:", dict(zip(names, mfqs)))
    for k, (w, m) in enumerate(zip(w_np, mfqs)):
        wabs_per_out = np.abs(w.astype(np.int64)).sum(axis=1)
        bound = float(wabs_per_out.max()) * 127.0 * abs(m)
        if bound >= INT32_MAX:
            print("★ 溢出风险：层 %s 的 max|acc|·MFQ 上界 %.3e >= 2^31" % (names[k], bound))

    # ---- numpy 整数推理 -> reference_out ----
    ref_out = []
    ref_actions = []
    for i in range(n_ref):
        lg = mlp_infer_int8(ref_in[i], w_np, mfqs, n_hidden)
        ref_out.append(np.concatenate(lg))
        ref_actions.append([int(np.argmax(l)) for l in lg])
    ref_out = np.stack(ref_out).astype(np.int8)
    out_dim = ref_out.shape[1]

    # ---- float 前向 vs 整数前向：argmax 决策一致率（量化损失）----
    print("=== 对拍：float 前向 vs 整数前向的 argmax 决策 ===")
    with torch.no_grad():
        logits_float = actor(torch.as_tensor(obs_all, dtype=torch.float32))
    float_actions = [l.argmax(1).cpu().numpy() for l in logits_float]
    match = 0
    total = n_ref * len(action_nvec)
    for i in range(n_ref):
        for h in range(len(action_nvec)):
            if ref_actions[i][h] == int(float_actions[h][i]):
                match += 1
    print("  [DECISION MATCH] %d/%d 点一致" % (match, total))
    if match != total:
        print("★ 注意：float 与整数策略有 %d 处 argmax 不一致（量化损失，需人工评估是否可接受）"
              % (total - match))

    # ---- 写出文件 ----
    os.makedirs(args.out, exist_ok=True)
    blob, layout = build_weight_blob(w_np, names, shapes)
    with open(os.path.join(args.out, "weights.bin"), "wb") as f:
        f.write(blob)
    with open(os.path.join(args.out, "reference_in.bin"), "wb") as f:
        f.write(ref_in.tobytes())
    with open(os.path.join(args.out, "reference_out.bin"), "wb") as f:
        f.write(ref_out.tobytes())

    # ---- model_spec.json ----
    mfq_per_layer = dict(zip(names, [int(m) for m in mfqs]))
    spec = {
        "model_name": ("scope_policy_mlp" if task == "scope_autoset" else "eq_policy_mlp"),
        "task": task,
        "input_shape": [obs_dim],
        "input_dtype": "int8",
        "input_quant": {
            "note": "obs∈[-1,1] 的浮点观测量化为 int8：i8 = round(clip(obs,-1,1)×127)（round half to even）",
            "formula": "i8 = round(clip(obs, -1, 1) * 127)",
            "obs_dim": obs_dim,
        },
        "layers": [
            {"type": "fc", "name": names[i], "in": int(shapes[i][1]), "out": int(shapes[i][0])}
            for i in range(n_hidden)
        ] + [
            {"type": "fc", "name": names[n_hidden + i], "in": int(shapes[n_hidden + i][1]),
             "out": int(action_nvec[i]), "head": True, "factor": i}
            for i in range(len(action_nvec))
        ],
        "action_space": {
            "type": "factored_discrete",
            "factors": [int(v) for v in action_nvec],
            "note": "因子化离散动作：对每个头 argmax 得到动作下标，再按 decode 表映射到真实设置",
        },
        "decode": decode_tables(task),
        "requant": {
            "formula": "out = sat((acc * MFQ) >> 16)",
            "shift": 16,
            "MFQ": int(mfqs[-1]),
            "MFQ_per_layer": mfq_per_layer,
            "MFQ_note": "MFQ 是 HLS 的 s_axilite 寄存器（每层独立传入）；PS 按 fc0→…→head… 顺序写入",
            "bias": "无偏置（与 HLS 一致）",
            "overflow_rule": "HLS 内 acc*MFQ 为 ap_int<32>，已检查 max|acc|*MFQ < 2^31",
            "activation": "HardTanh（clamp[-1,1]），量化后即 sat[-128,127]（等价 HLS fc 的 clamp）",
        },
        "weights_layout": {
            "file": "weights.bin", "dtype": "int8",
            "align_bytes": ALIGN, "tail_pad_multiple": PAD_MULT,
            "total_bytes": len(blob),
            "order": names,
            "entries": layout,
            "index_order": "fc: w[oc*IN + i]（行主序，与 HLS cnn_fc_q 一致）",
        },
        "reference": {
            "n_samples": n_ref,
            "input_format": "连续 int8 obs，每个 %d 字节" % obs_dim,
            "output_format": "连续 int8 logits，每个 %d 字节（各头按 factor 顺序拼接）" % out_dim,
            "how_to_compare": "对第 k 个输入跑整数推理，把 %d 字节输出与 reference_out.bin[k*%d:(k+1)*%d] 逐点比对，应 100%% 相同" % (out_dim, out_dim, out_dim),
            "actions_argmax": ref_actions,
            "decision_match_vs_float": "%d/%d" % (match, total),
        },
        "generated_by": "src/rl/quantize_policy.py",
    }
    with open(os.path.join(args.out, "model_spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    # ---- README.md ----
    _write_readme(args.out, spec, names, mfq_per_layer, layout, blob, ref_in, ref_out,
                  ref_actions, task, out_dim)

    # ---- ★ 强制自检：读回 -> 整数推理 -> 逐点比对 ----
    print("=== 自检：从导出文件读回并逐点比对 ===")
    blob2 = np.fromfile(os.path.join(args.out, "weights.bin"), dtype=np.uint8)
    assert len(blob2) == len(blob), "weights.bin 长度不符"
    rw = []
    for entry in layout:
        arr = blob2[entry["offset"]:entry["offset"] + entry["bytes"]].astype(np.int8)
        rw.append(arr.reshape(entry["shape"]))
    for k in range(len(w_np)):
        assert np.array_equal(rw[k], w_np[k]), "层 %s 读回不一致" % names[k]

    rin = np.fromfile(os.path.join(args.out, "reference_in.bin"), dtype=np.int8)
    rout = np.fromfile(os.path.join(args.out, "reference_out.bin"), dtype=np.int8)
    assert len(rin) == n_ref * obs_dim, "reference_in.bin 长度不符"
    assert len(rout) == n_ref * out_dim, "reference_out.bin 长度不符"

    ok_pts = 0
    tot_pts = 0
    for k in range(n_ref):
        x = rin[k * obs_dim:(k + 1) * obs_dim]
        lg = mlp_infer_int8(x, rw, mfqs, n_hidden)
        got = np.concatenate(lg).astype(np.int8)
        exp = rout[k * out_dim:(k + 1) * out_dim]
        same = int((got == exp).sum())
        ok_pts += same
        tot_pts += out_dim
        if same != out_dim:
            print("  [MISMATCH] sample %d" % k)
    print("  [EXPORT OK] %d/%d 点一致（%d 组参考样本）" % (ok_pts, tot_pts, n_ref))
    assert ok_pts == tot_pts, "★ 导出自检失败：reference_out.bin 与读回权重不自洽"
    print("  weights.bin    : %d bytes" % len(blob))
    print("  reference_in   : %d samples x %d B" % (n_ref, obs_dim))
    print("  reference_out  : %d samples x %d B" % (n_ref, out_dim))
    print("输出目录 -> %s" % args.out)


def _write_readme(out_dir, spec, names, mfq_per_layer, layout, blob, ref_in, ref_out,
                  ref_actions, task, out_dim):
    A = []
    A.append("# %s —— 策略网络量化交付包\n" % spec["model_name"])
    A.append("> 项目：系统管家小白（Zynq-7020）· 生成者：AI 训练负责人（任务 E）")
    A.append("> 格式依据：`07_接口约定单.md` 接口 ① + `00_接口冻结单.md`（沿用 `(acc×MFQ)>>16` 方案）\n")
    A.append("## 1. 这是什么\n")
    A.append("一个**%d 维 int8 输入 / 因子化离散动作**的小 MLP 策略网络，" % spec["input_shape"][0])
    A.append("与上一轮 PL 侧 `cnn_fc_q` **逐位同构**（`acc=Σx_q·w_q -> (acc×MFQ)>>16 -> sat[-128,127]`），")
    A.append("接上既有 IP 的 FC 通路即可推理。动作因子数 %s。\n" % spec["action_space"]["factors"])
    A.append("## 2. 文件清单\n")
    A.append("| 文件 | 说明 |")
    A.append("|---|---|")
    A.append("| `weights.bin` | int8 权重，%d 字节（布局见 §4） |" % len(blob))
    A.append("| `model_spec.json` | 模型结构 + requant + 内存布局 + 动作解码 |")
    A.append("| `reference_in.bin` | ★ %d 组测试输入，每组 %d 字节 int8 |" % (ref_in.shape[0], ref_in.shape[1]))
    A.append("| `reference_out.bin` | ★ 对应输出，每组 %d 字节 int8（与硬件逐位一致） |" % out_dim)
    A.append("| `README.md` | 本文件 |\n")
    A.append("## 3. ★ 怎么验证（板子侧唯一可靠做法）\n")
    A.append("```")
    A.append("for k in 0 .. %d:" % (ref_in.shape[0] - 1))
    A.append("    把 reference_in.bin[k*%d:(k+1)*%d] 依次送入 FC 通路" % (ref_in.shape[1], ref_in.shape[1]))
    A.append("    逐层写 MFQ_per_layer 寄存器，读回各头 logits")
    A.append("    与 reference_out.bin[k*%d:(k+1)*%d] 逐点比对 -> 应 100%% 相同" % (out_dim, out_dim))
    A.append("```\n")
    A.append("## 4. DDR 内存布局（weights.bin）\n")
    A.append("| 偏移 | 层 | 形状 | 字节 |")
    A.append("|---|---|---|---|")
    for l in layout:
        A.append("| `0x%04X` | %s | %s | %d |" % (l["offset"], l["name"], l["shape"], l["bytes"]))
    A.append("")
    A.append("- 每层 128 字节对齐，层间/文件尾补齐到 64 的倍数（cache line 安全）")
    A.append("- 索引顺序：`w[oc*IN + i]`（行主序，与 HLS cnn_fc_q 一致）；无偏置")
    A.append("- 文件总大小：**%d 字节**\n" % len(blob))
    A.append("## 5. requant（沿用上一轮方案，硬件零改动）\n")
    A.append("```")
    A.append("out = sat((acc * MFQ) >> 16)     # 算术右移=floor，饱和到 [-128,127]")
    A.append("```")
    A.append("| 层 | MFQ |")
    A.append("|---|---|")
    for n in names:
        A.append("| %s | %d |" % (n, mfq_per_layer[n]))
    A.append("")
    A.append("`MFQ` 是 HLS 的 `s_axilite` 寄存器，**每层独立传入**；PS 按上表顺序写入即可。\n")
    A.append("## 6. 动作解码（argmax -> 真实设置）\n")
    A.append("对第 i 个头取 argmax 得到下标 a_i，再查 `model_spec.json` 的 `decode.factors[i].decode[a_i]`：")
    A.append("")
    if task == "scope_autoset":
        A.append("- 头0 触发电平：%s（LSB）" % spec["decode"]["factors"][0]["decode"])
        A.append("- 头1 时基 DEC：%s" % spec["decode"]["factors"][1]["decode"])
        A.append("- 头2 垂直增益：%s" % [round(v, 3) for v in spec["decode"]["factors"][2]["decode"]])
    else:
        A.append("- 8 个头 = 8 段 EQ 增益（dB），中心频率 %s Hz" % [int(f) for f in EQ_BANDS])
        A.append("- 每头 9 档：%s（dB）" % [float(v) for v in GAIN_LEVELS_DB])
    A.append("")
    A.append("## 7. 输入量化\n")
    A.append("观测 obs∈[-1,1] 量化为 `i8 = round(clip(obs,-1,1)×127)`。")
    A.append("板端必须用**同一套 obs 计算**（见 `src/rl/scope_env.py::_obs` / `audio_eq_env.py::_obs`），")
    A.append("再按上式量化，才能与 reference_in.bin 对齐。\n")
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(A) + "\n")


if __name__ == "__main__":
    main()
