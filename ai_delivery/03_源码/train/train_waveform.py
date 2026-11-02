"""
train_waveform.py —— 任务 C：波形识别模型②（训练 → 量化 → 导出）

流程（三阶段，可复现）：
  P1 浮点预训练   : 同尺度（x = u8-128）下训练一个 bias=False 的小 CNN
  P2 量化校准     : 逐层定 s_w = max|W|/127，并标定激活步长 s_y
  P3 硬件同构 QAT : 用**逐位等于硬件**的整数前向做量化感知微调，损失用真整数 logits
  评估            : ① torch 整数前向准确率 ② numpy 参考实现（硬件复刻）准确率，
                    两者必须完全一致 —— 这是"reference_out.bin 可信"的证据

用法（在 lab415 上）：
  python train_waveform.py --data /data/.../dataset --out /data/.../runs/wavenet_v1 \
      --epochs-float 40 --epochs-qat 30 --seed 20261001
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "common"))

from qmodel import QWaveNet, diagnose, reference_infer_arrays, IMG          # noqa: E402

CLASSES = ["sine", "square", "triangle", "sawtooth", "noise",
           "glitch", "clipping", "signal_loss", "duty_abnormal"]


# ===========================================================================
# 数据
# ===========================================================================
def load_packed(data_dir: str, split: str):
    p = os.path.join(data_dir, "packed")
    img = np.load(os.path.join(p, "img_%s.npy" % split))
    lab = np.load(os.path.join(p, "label_%s.npy" % split))
    if img.ndim == 4 and img.shape[1] == 1:
        pass
    img = img.astype(np.uint8)
    return img, lab.astype(np.int64)


def load_pp_mode(data_dir: str) -> str:
    """★ 输入表示必须从数据集的 meta.json 读（数据集是契约的权威来源）"""
    p = os.path.join(data_dir, "meta.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("input_type", "wdens")
    return "wdens"


def load_classes(data_dir: str):
    """★ 类别表同样从 meta.json 读（默认 8 类，不含毛刺 —— 见 dds_sim.CLASSES_REQUIRING_PL）"""
    p = os.path.join(data_dir, "meta.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cls = json.load(f).get("classes")
        if cls:
            return list(cls)
    return list(CLASSES)


def augment(img_u8: np.ndarray, rng: np.random.Generator, pp: str = "wdens") -> np.ndarray:
    """
    ★ 图像域数据增强。全部在 uint8 输入域上做，保证送进加速器前仍是合法 int8。

    ★★ 必须按【输入表示】选对应的几何变换 —— 两种表示的行语义完全不同：
        stft : 行 = 对数频率  ⇒ 行平移 = 谐波梳整体平移（基频/采样率变化）
        wdens: 行 = 幅度      ⇒ 行平移/缩放 = 偏置/增益变化（以中心行做仿射）
      在 wdens 上做行循环平移是**错误**的（会把高幅度折到底部），必须避免。
    """
    x = img_u8.astype(np.int16)

    if pp == "stft":
        # ---- 频率轴平移：对数频率轴上的倍频程平移 == 行平移 ----
        if rng.random() < 0.8:
            sh = int(rng.integers(-4, 5))
            if sh:
                x = np.roll(x, sh, axis=2)
                if sh > 0:                      # reflect 边界，避免环绕伪影
                    x[:, :, :sh, :] = x[:, :, sh:sh + 1, :]
                else:
                    x[:, :, sh:, :] = x[:, :, sh - 1:sh, :]
    else:
        # ---- 幅度轴仿射：以中心行 (IMG-1)/2 为基准做缩放 + 平移 ----
        # ★★ 必须用【最大值重采样】而不是最近邻：
        #    毛刺在密度图里常常只有 1 个像素，最近邻重采样会把某些源行整行丢掉，
        #    等于把毛刺擦掉 —— 第一版就是这样，导致 glitch 这一类几乎学不到。
        if rng.random() < 0.85:
            g = float(rng.uniform(0.82, 1.22))          # 增益变化
            sh = float(rng.uniform(-2.5, 2.5))          # 直流偏置变化
            c = (IMG - 1) / 2.0
            src_r = np.arange(IMG, dtype=np.float64)
            lo = np.rint(c + (src_r - 0.5 - c) / g + sh).astype(np.int64)
            hi = np.rint(c + (src_r + 0.5 - c) / g + sh).astype(np.int64)
            hi = np.maximum(hi, lo + 1)
            lo = np.clip(lo, 0, IMG)
            hi = np.clip(hi, 0, IMG)
            out = np.zeros_like(x)
            for r in range(IMG):
                a, b = int(lo[r]), int(hi[r])
                out[:, :, r, :] = x[:, :, a:b, :].max(axis=2) if b > a else 0
            x = out

    # ---- 时间轴平移：两种表示都成立（触发点/相位随机）----
    if rng.random() < 0.6:
        sh = int(rng.integers(-3, 4))
        if sh:
            x = np.roll(x, sh, axis=3)

    if pp == "stft":
        # STFT 是 dB 域图像，亮度/增益抖动近似"整体电平变化"
        if rng.random() < 0.7:
            x = np.rint(x * rng.uniform(0.85, 1.18) + rng.uniform(-10, 10))

    if rng.random() < 0.7:                              # 加性噪声（两种表示都可）
        # ★ 控制在 ≤3 LSB：太强的图像噪声会把"毛刺"这种细微信号淹掉
        s = float(rng.uniform(0.0, 3.0))
        if s > 0:
            x = np.rint(x + rng.normal(0, s, size=x.shape))

    return np.clip(x, 0, 255).astype(np.uint8)


def focal_ce(logits, target, gamma=1.0, ls=0.02):
    """
    Focal loss（+ label smoothing）。
    ★ 为什么需要：毛刺/占空比异常这类"细微信号"样本在 9 类里占比不高，
       普通 CE 会被干净波形主导，模型退化成"只看底波形"。focal 把梯度
       集中到还没学会的难样本上。gamma=0 退化为普通 CE。
    """
    ce = F.cross_entropy(logits, target, reduction="none", label_smoothing=ls)
    if gamma <= 0:
        return ce.mean()
    with torch.no_grad():
        p = F.softmax(logits.float(), dim=1).gather(1, target[:, None]).squeeze(1)
    return ((1.0 - p).pow(gamma) * ce).mean()


def make_batches(img, lab, bs, rng, train=True, device="cuda", pp="wdens"):
    idx = rng.permutation(len(img)) if train else np.arange(len(img))
    for i in range(0, len(idx), bs):
        b = idx[i:i + bs]
        xb = img[b]
        if train:
            xb = augment(xb, rng, pp)
        yield (torch.from_numpy(xb).to(device, non_blocking=True).float(),
               torch.from_numpy(lab[b]).to(device, non_blocking=True))


# ===========================================================================
# 浮点预训练前向（同尺度：x = u8 - 128）
# ===========================================================================
def float_forward(model: QWaveNet, x_u8: torch.Tensor) -> torch.Tensor:
    x = x_u8 - 128.0
    a = F.relu(F.conv2d(x, model.conv1.weight, bias=None))
    a = F.max_pool2d(a, 2)
    b = F.relu(F.conv2d(a, model.conv2.weight, bias=None))
    b = F.max_pool2d(b, 2)
    return F.linear(b.flatten(1), model.fc.weight)


@torch.no_grad()
def evaluate(model, img, lab, bs=512, device="cuda", use_reference=False, pp="wdens"):
    model.eval()
    correct = 0
    n = 0
    preds = []
    for xb, yb in make_batches(img, lab, bs, np.random.default_rng(0), train=False,
                               device=device, pp=pp):
        logits = model.quant_forward(xb)["logits"]
        p = logits.argmax(dim=1)
        preds.append(p.cpu().numpy())
        correct += int((p == yb).sum())
        n += len(yb)
    preds = np.concatenate(preds) if preds else np.zeros(0)
    acc = correct / max(1, n)
    out = {"acc": acc, "n": n, "pred": preds}
    if use_reference:
        # ★ 用 numpy 硬件复刻再过一遍，验证 torch 整数前向 == 硬件语义
        iw = model.int_weights()
        w1 = iw["conv1.weight"].cpu().numpy()
        w2 = iw["conv2.weight"].cpu().numpy()
        wf = iw["fc.weight"].cpu().numpy()
        mfq = model.mfq_list()
        ref_pred = np.empty(len(img), dtype=np.int64)
        for i in range(len(img)):
            lg, _, _ = reference_infer_arrays(img[i], w1, w2, wf, mfq)
            ref_pred[i] = int(np.argmax(lg))
        out["ref_acc"] = float((ref_pred == lab).mean())
        out["ref_matches_torch"] = bool(np.array_equal(ref_pred, preds))
        out["ref_pred"] = ref_pred
    return out


def confusion(pred, lab, k=9):
    cm = np.zeros((k, k), dtype=np.int64)
    for p, t in zip(pred, lab):
        cm[int(t), int(p)] += 1
    return cm


@torch.no_grad()
def evaluate_float(model, img, lab, bs=512, device="cuda"):
    """
    ★ 浮点路径的准确率 —— 这才是"量化损失"的对照基准。
      （第一版把量化模型自己的准确率当成了浮点基线，导致报告里
        "量化损失 0.0000" 是个假结论，必须修。）
    """
    model.eval()
    correct, n = 0, 0
    for xb, yb in make_batches(img, lab, bs, np.random.default_rng(0),
                               train=False, device=device):
        logits = float_forward(model, xb)
        correct += int((logits.argmax(1) == yb).sum())
        n += len(yb)
    return correct / max(1, n), n


# ===========================================================================
# main
# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--epochs-float", type=int, default=40)
    ap.add_argument("--epochs-qat", type=int, default=30)
    ap.add_argument("--bs", type=int, default=256)
    ap.add_argument("--lr-float", type=float, default=3e-3)
    ap.add_argument("--lr-qat", type=float, default=3e-4)
    ap.add_argument("--lr-scale", type=float, default=3e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="focal loss 的 gamma；0 = 普通交叉熵")
    ap.add_argument("--calib-pct", type=float, default=99.9,
                    help="激活标定分位数；100 = 按 max 标定（dead zone 最大）")
    ap.add_argument("--fix-mfq", type=int, default=0, help=">0 时全层用同一 MFQ（兼容模式）")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--limit-train", type=int, default=0)
    ap.add_argument("--no-reference-eval", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    device = "cuda:%d" % args.gpu if torch.cuda.is_available() else "cpu"

    # ---- 可复现性：固定所有随机源 ----
    seed = args.seed
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    rng = np.random.default_rng(seed)

    print("=== 任务C：波形识别模型② 训练 ===")
    print("device :", device, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    print("data   :", args.data)
    print("out    :", args.out)

    pp = load_pp_mode(args.data)          # ★ 输入表示取自数据集 meta.json
    classes = load_classes(args.data)     # ★ 类别表取自数据集 meta.json
    print("input_type :", pp)
    print("classes    :", classes)

    xtr, ytr = load_packed(args.data, "train")
    xva, yva = load_packed(args.data, "val")
    xte, yte = load_packed(args.data, "test")
    if args.limit_train:
        xtr, ytr = xtr[:args.limit_train], ytr[:args.limit_train]
    print("shapes :", xtr.shape, xva.shape, xte.shape)

    model = QWaveNet(n_classes=len(classes), fix_mfq=(args.fix_mfq or None)).to(device)

    hist = {"args": vars(args), "input_type": pp, "classes": classes,
            "stages": {}}

    # ---------------- P1 浮点预训练 ----------------
    print("\n--- P1 浮点预训练 (%d epochs) ---" % args.epochs_float)
    model.set_activations_warm(True)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr_float, weight_decay=args.wd)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr_float, total_steps=args.epochs_float * max(1, len(xtr) // args.bs),
        pct_start=0.25)
    t0 = time.time()
    for ep in range(args.epochs_float):
        model.train()
        tot, cor, loss_sum = 0, 0, 0.0
        for xb, yb in make_batches(xtr, ytr, args.bs, rng, train=True, device=device, pp=pp):
            logits = float_forward(model, xb)
            loss = focal_ce(logits, yb, gamma=args.gamma)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            try:
                sched.step()
            except Exception:
                pass
            loss_sum += float(loss) * len(yb)
            cor += int((logits.argmax(1) == yb).sum())
            tot += len(yb)
        if (ep + 1) % 5 == 0 or ep == 0:
            ev = evaluate(model, xva, yva, device=device, pp=pp) if False else None
            print("  ep %3d  train_acc %.4f  loss %.4f  %.0fs"
                  % (ep + 1, cor / tot, loss_sum / tot, time.time() - t0), flush=True)
    hist["stages"]["p1_float"] = {"train_acc": cor / tot, "seconds": time.time() - t0}
    # ★ 浮点基线必须在【纯浮点阶段刚结束时】测 ——
    #   事后用"QAT 权重的浮点视图"当基线是错的（那些权重是为整数前向优化的，
    #   浮点视图反而更差，会得出"量化损失为负"的怪结论）。
    _fl_va, _ = evaluate_float(model, xva, yva, device=device)
    _fl_te, _ = evaluate_float(model, xte, yte, device=device)
    hist["stages"]["p1_float"]["val_acc"] = _fl_va
    hist["stages"]["p1_float"]["test_acc"] = _fl_te
    print("  P1 结束（纯浮点）：val_acc %.4f  test_acc %.4f" % (_fl_va, _fl_te))
    torch.save(model.state_dict(), os.path.join(args.out, "ckpt_p1_float.pt"))

    # ---------------- P2 校准 ----------------
    print("\n--- P2 量化校准 ---")
    model.set_activations_warm(False)
    model.init_all_scales()
    xcal = torch.from_numpy(xtr[:2048]).to(device).float()
    acc_max = model.calibrate(xcal, iters=3, percentile=args.calib_pct)
    mfq0 = model.mfq_list()
    print("  标定分位数: %.3g  分位值: %s"
          % (args.calib_pct,
             [round(v, 1) for v in getattr(model, "_calib_pct", [])]))
    print("  max|acc|  :", [round(v, 1) for v in acc_max])
    print("  MFQ       :", mfq0)
    print("  s_w       :", [round(model.conv1.s_w_val(), 6),
                            round(model.conv2.s_w_val(), 6),
                            round(model.fc.s_w_val(), 8)])
    print("  s_y       :", [round(model.conv1.s_y_val(), 4),
                            round(model.conv2.s_y_val(), 4),
                            round(model.fc.s_y_val(), 4)])
    for i, v in enumerate(acc_max):
        print("  layer%d  int32 溢出余量 %.1fx  (acc*MFQ=%.3g)" %
              (i + 1, (2 ** 31 - 1) / max(1.0, v * mfq0[i]), v * mfq0[i]))
    torch.save(model.state_dict(), os.path.join(args.out, "ckpt_p2_calib.pt"))

    # ---------------- P3 硬件同构 QAT ----------------
    print("\n--- P3 硬件同构 QAT (%d epochs) ---" % args.epochs_qat)
    scale_params = [model.conv1.log2_sw, model.conv1.log2_sy,
                    model.conv2.log2_sw, model.conv2.log2_sy,
                    model.fc.log2_sw, model.fc.log2_sy]
    wparams = [model.conv1.weight, model.conv2.weight, model.fc.weight]
    opt = torch.optim.AdamW([
        {"params": wparams, "lr": args.lr_qat, "weight_decay": args.wd},
        {"params": scale_params, "lr": args.lr_scale, "weight_decay": 0.0},
    ])
    steps = args.epochs_qat * max(1, len(xtr) // args.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[args.lr_qat, args.lr_scale],
                                                total_steps=steps, pct_start=0.2)
    t0 = time.time()
    best = -1.0
    for ep in range(args.epochs_qat):
        model.train()
        tot, cor, loss_sum = 0, 0, 0.0
        for xb, yb in make_batches(xtr, ytr, args.bs, rng, train=True, device=device, pp=pp):
            logits = model.quant_forward(xb)["logits"]
            loss = focal_ce(logits, yb, gamma=args.gamma)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            try:
                sched.step()
            except Exception:
                pass
            loss_sum += float(loss) * len(yb)
            cor += int((logits.argmax(1) == yb).sum())
            tot += len(yb)
        if (ep + 1) % 5 == 0 or ep == args.epochs_qat - 1:
            ev = evaluate(model, xva, yva, device=device, pp=pp)
            print("  ep %3d  train_acc %.4f  val_acc %.4f  loss %.4f  MFQ %s  %.0fs"
                  % (ep + 1, cor / tot, ev["acc"], loss_sum / tot,
                     model.mfq_list(), time.time() - t0), flush=True)
            if ev["acc"] > best:
                best = ev["acc"]
                torch.save(model.state_dict(), os.path.join(args.out, "ckpt_best.pt"))
    hist["stages"]["p3_qat"] = {"best_val_acc": best, "seconds": time.time() - t0}
    torch.save(model.state_dict(), os.path.join(args.out, "ckpt_final.pt"))

    # ---------------- 评估 ----------------
    print("\n--- 评估 ---")
    if os.path.exists(os.path.join(args.out, "ckpt_best.pt")):
        model.load_state_dict(torch.load(os.path.join(args.out, "ckpt_best.pt"), map_location=device))
    ev_te = evaluate(model, xte, yte, device=device, pp=pp,
                     use_reference=not args.no_reference_eval)
    ev_tr = evaluate(model, xtr[:5000], ytr[:5000], device=device, pp=pp)
    # ★ 浮点基线：同一套权重、关掉量化跑一遍 —— 这才是"量化损失"的分母
    fl_te, _ = evaluate_float(model, xte, yte, device=device)
    fl_tr, _ = evaluate_float(model, xtr[:5000], ytr[:5000], device=device)
    print("  test_acc(torch 整数前向) = %.4f  (n=%d)" % (ev_te["acc"], ev_te["n"]))
    if "ref_acc" in ev_te:
        print("  test_acc(numpy 硬件复刻) = %.4f  | 与 torch 完全一致: %s"
              % (ev_te["ref_acc"], ev_te["ref_matches_torch"]))
    print("  test_acc(浮点路径)       = %.4f   ⇒ 量化损失 %.4f"
          % (fl_te, fl_te - ev_te["acc"]))
    print("  train_acc(前5000)        = %.4f (整数) / %.4f (浮点)"
          % (ev_tr["acc"], fl_tr))

    diag = diagnose(model, torch.from_numpy(xte[:1024]).to(device).float())
    print("  MFQ           :", diag["mfq"])
    print("  |acc|max      :", [round(v, 1) for v in diag["acc_absmax"]])
    print("  溢出风险      :", diag["overflow_risk"], " 余量:",
          [round(v, 1) for v in diag["int32_headroom"]])
    print("  饱和率        :", {k: {kk: round(vv, 4) for kk, vv in v.items()}
                                for k, v in diag["saturation_frac"].items()})
    print("  权重用量化级数:", diag["w_int_used_levels"])

    cm = confusion(ev_te["pred"], yte, k=len(classes))
    print("\n  混淆矩阵 (行=真值, 列=预测):")
    print("        " + "".join("%8s" % c[:7] for c in classes))
    for i, c in enumerate(classes):
        print("  %-8s" % c[:7] + "".join("%8d" % v for v in cm[i]))

    # ---- 保存模型（float state，供导出脚本用） ----
    torch.save(model.state_dict(), os.path.join(args.out, "model_final.pt"))
    np.save(os.path.join(args.out, "test_pred.npy"), ev_te["pred"])

    hist["final"] = {
        "test_acc_torch": ev_te["acc"],
        "test_acc_reference": ev_te.get("ref_acc"),
        "reference_matches_torch": ev_te.get("ref_matches_torch"),
        "test_acc_float": hist["stages"]["p1_float"]["test_acc"],
        "test_acc_float_qat_weights": fl_te,
        "quantization_loss": float(hist["stages"]["p1_float"]["test_acc"] - ev_te["acc"]),
        "train_acc": ev_tr["acc"],
        "train_acc_float": fl_tr,
        "mfq": diag["mfq"],
        "calib_percentile": args.calib_pct,
        "diagnose": {k: v for k, v in diag.items()},
        "confusion": cm.tolist(),
        "classes": classes,
    }
    with open(os.path.join(args.out, "train_report.json"), "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    print("\n报告 ->", os.path.join(args.out, "train_report.json"))
    print("模型 ->", os.path.join(args.out, "model_final.pt"))


if __name__ == "__main__":
    main()
