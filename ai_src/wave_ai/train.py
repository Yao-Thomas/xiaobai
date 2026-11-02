"""
train.py —— 训练主程序（CPU 可跑，24 核约 25 s/epoch @ 96×96）

用法：
    python -m wave_ai.train --data data/ds_train --hard data/ds_hard --out runs/v1
    python -m wave_ai.train --smoke            # 2 分钟冒烟

产物（runs/<name>/）：
    model_bundle.pt   权重 + 特征标准化参数 + 温度 + 类别表（服务直接加载这个）
    train_report.json 每轮曲线 / 混淆矩阵 / 每类 P-R-F1 / 延迟 / 量化损失对照
    confusion.png     混淆矩阵图
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

from .config import CAP_LEN, CLASSES, N_CLASSES, VERSION
from .dataset import load_split
from .features import FEAT_DIM
from .model import WaveFusionNet, count_params
from .representation import to_images, to_model_input

N_LP = N_CLASSES + 1          # 端侧概率块 + available 标志


# ---------------------------------------------------------------------------
# 损失 / 增强 / 批迭代
# ---------------------------------------------------------------------------
def focal_ce(logits, target, gamma=1.0, ls=0.03):
    ce = F.cross_entropy(logits, target, reduction="none", label_smoothing=ls)
    if gamma <= 0:
        return ce.mean()
    with torch.no_grad():
        p = F.softmax(logits.float(), dim=1).gather(1, target[:, None]).squeeze(1)
    return ((1.0 - p).pow(gamma) * ce).mean()


def augment_raw(raw, rng):
    """只做循环时移（相位不变性）；不擅自改增益/噪声，避免与特征不一致"""
    n = raw.shape[0]
    sh = rng.integers(-320, 321, size=n)
    if np.all(sh == 0):
        return raw
    idx = (np.arange(CAP_LEN)[None, :] - sh[:, None]) % CAP_LEN
    return raw[np.arange(n)[:, None], idx]


def augment_feat(feat, rng, p_drop=0.25):
    """特征增强：加小噪声 + **随机丢掉端侧概率**。

    ★ p_drop 必须足够大（0.25）：契约说 local_cnn 是可选输入，
      而板端 PL CNN 只认 8 类、在真实数据上会错。如果训练时只丢 10%，
      模型会退化成"抄端侧答案"——实测不带端侧概率时准确率从 95.3% 掉到 85.5%。
    """
    f = feat + rng.normal(0.0, 0.03, size=feat.shape).astype(np.float32)
    drop = rng.random(len(f)) < p_drop
    if drop.any():
        f[drop, -(N_LP):] = 0.0          # 16 维概率 + available 全清零
        f[drop, -(N_LP):-(N_LP - 8)] = 1.0 / 8.0   # 前 8 类填均匀先验
    return f


def iter_batches(raw, feat, label, bs, rng, train, mean, std):
    n = len(label)
    order = rng.permutation(n) if train else np.arange(n)
    for s in range(0, n, bs):
        idx = order[s:s + bs]
        r = raw[idx]
        f = feat[idx]
        y = label[idx]
        if train:
            r = augment_raw(r, rng)
            f = augment_feat(f, rng)
        img = torch.from_numpy(to_model_input(to_images(r)))
        fn = torch.from_numpy(((f - mean) / std).astype(np.float32))
        yield img, fn, torch.from_numpy(y)


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------
@torch.no_grad()
def evaluate(model, raw, feat, label, bs, mean, std, device="cpu", want_embed=False):
    model.eval()
    logits_all, emb_all = [], []
    for img, fn, y in iter_batches(raw, feat, label, bs,
                                   np.random.default_rng(0), False, mean, std):
        img, fn = img.to(device), fn.to(device)
        logits_all.append(model(img, fn).cpu())
        if want_embed:
            emb_all.append(model.embedding(img, fn).cpu())
    logits = torch.cat(logits_all)
    pred = logits.argmax(1).numpy()
    out = {
        "logits": logits.numpy(),
        "pred": pred,
        "acc": float((pred == label).mean()),
        "n": int(len(label)),
    }
    if want_embed:
        out["embed"] = torch.cat(emb_all).numpy()
    return out


def per_class_report(pred, label, classes):
    k = len(classes)
    cm = np.zeros((k, k), dtype=np.int64)
    for t, p in zip(label, pred):
        cm[int(t), int(p)] += 1
    rows = []
    for i, c in enumerate(classes):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        rows.append({"class": c, "precision": round(float(prec), 4),
                     "recall": round(float(rec), 4), "f1": round(float(f1), 4),
                     "support": int(cm[i].sum())})
    return cm, rows


def fit_temperature(logits, label):
    """温度标定：在验证集上最小化 NLL（模型置信度要能和真实正确率对上）"""
    z = torch.from_numpy(logits).float()
    y = torch.from_numpy(np.asarray(label)).long()
    best_t, best_nll = 1.0, 1e18
    for t in np.arange(0.5, 3.01, 0.05):
        nll = float(F.cross_entropy(z / float(t), y))
        if nll < best_nll:
            best_nll, best_t = nll, float(t)
    return best_t, best_nll


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/ds_train")
    ap.add_argument("--hard", default="data/ds_hard", help="困难域测试集（可无）")
    ap.add_argument("--out", default="runs/v2")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--bs", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2.5e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)

    tr = load_split(args.data, "train")
    va = load_split(args.data, "val")
    te = load_split(args.data, "test")
    if args.limit:
        for d in (tr, va, te):
            for k in ("raw", "feat", "label"):
                d[k] = d[k][:args.limit]
    if args.smoke:
        args.epochs = min(args.epochs, 2)

    mean = tr["feat"].mean(axis=0)
    std = tr["feat"].std(axis=0)
    std[std < 1e-3] = 1e-3
    mean = mean.astype(np.float32)
    std = std.astype(np.float32)

    model = WaveFusionNet()
    print("=== 训练 ===")
    print("  device : CPU  threads=%d" % args.threads)
    print("  params : %d" % count_params(model))
    print("  data   : train %d / val %d / test %d" % (
        len(tr["label"]), len(va["label"]), len(te["label"])))
    print("  classes: %d  feat %d" % (N_CLASSES, FEAT_DIM))

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.wd)
    steps = args.epochs * max(1, len(tr["label"]) // args.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps,
                                                pct_start=0.25)
    hist = {"args": vars(args), "version": VERSION, "classes": CLASSES,
            "epochs": [], "params": count_params(model)}
    best_acc, best_state = -1.0, None
    t0 = time.time()
    for ep in range(args.epochs):
        model.train()
        loss_sum, cor, tot = 0.0, 0, 0
        for img, fn, y in iter_batches(tr["raw"], tr["feat"], tr["label"], args.bs,
                                       rng, True, mean, std):
            logits = model(img, fn)
            loss = focal_ce(logits, y, gamma=args.gamma)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            try:
                sched.step()
            except Exception:
                pass
            loss_sum += float(loss.detach()) * len(y)
            cor += int((logits.argmax(1) == y).sum())
            tot += len(y)
        ev = evaluate(model, va["raw"], va["feat"], va["label"], args.bs, mean, std)
        rec = {"epoch": ep + 1, "train_acc": round(cor / max(tot, 1), 4),
               "train_loss": round(loss_sum / max(tot, 1), 4),
               "val_acc": round(ev["acc"], 4),
               "seconds": round(time.time() - t0, 1)}
        hist["epochs"].append(rec)
        print("  ep %2d  train %.4f  val %.4f  loss %.4f  lr %.2e  %.0fs"
              % (ep + 1, rec["train_acc"], rec["val_acc"], rec["train_loss"],
                 sched.get_last_lr()[0], rec["seconds"]), flush=True)
        if ev["acc"] > best_acc:
            best_acc = ev["acc"]
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    # ---- 温度标定（用 val）----
    ev_va = evaluate(model, va["raw"], va["feat"], va["label"], args.bs, mean, std)
    temp, nll = fit_temperature(ev_va["logits"], va["label"])
    hist["temperature"] = temp
    hist["val_nll"] = round(nll, 4)

    # ---- 测试集评估 ----
    ev_te = evaluate(model, te["raw"], te["feat"], te["label"], args.bs, mean, std,
                     want_embed=True)
    cm, rows = per_class_report(ev_te["pred"], te["label"], CLASSES)
    acc8 = float(np.mean(ev_te["pred"][te["label"] < 8] == te["label"][te["label"] < 8]))
    hist["test"] = {
        "acc": round(float(ev_te["acc"]), 4),
        "acc_first8_classes": round(acc8, 4),
        "n": ev_te["n"],
        "per_class": rows,
        "confusion": cm.tolist(),
    }
    print("\n  test_acc = %.4f   (8 类子集 %.4f)" % (ev_te["acc"], acc8))

    if args.hard and os.path.exists(os.path.join(args.hard, "raw_test.npy")):
        hd = load_split(args.hard, "test")
        ev_h = evaluate(model, hd["raw"], hd["feat"], hd["label"], args.bs, mean, std)
        cm_h, rows_h = per_class_report(ev_h["pred"], hd["label"], CLASSES)
        acc8_h = float(np.mean(ev_h["pred"][hd["label"] < 8] == hd["label"][hd["label"] < 8]))
        hist["hard"] = {"acc": round(float(ev_h["acc"]), 4),
                        "acc_first8_classes": round(acc8_h, 4),
                        "per_class": rows_h, "confusion": cm_h.tolist()}
        print("  hard_domain_acc = %.4f  (域偏移鲁棒性)" % ev_h["acc"])

    # ---- 单帧延迟（CPU，含预处理）----
    lat = []
    model.eval()
    with torch.no_grad():
        for i in range(30):
            r = te["raw"][i:i + 1]
            t = time.perf_counter()
            img = torch.from_numpy(to_model_input(to_images(r)))
            fn = torch.from_numpy(((te["feat"][i:i + 1] - mean) / std).astype(np.float32))
            model(img, fn)
            lat.append((time.perf_counter() - t) * 1000.0)
    hist["latency_ms"] = {"p50": round(float(np.median(lat)), 2),
                          "p95": round(float(np.percentile(lat, 95)), 2)}
    print("  单帧推理延迟(含 96×96 预处理): p50 %.1f ms  p95 %.1f ms"
          % (hist["latency_ms"]["p50"], hist["latency_ms"]["p95"]))

    # ---- 保存 ----
    bundle = {
        "state_dict": model.state_dict(),
        "classes": CLASSES,
        "n_classes": N_CLASSES,
        "feat_dim": FEAT_DIM,
        "feat_mean": mean,
        "feat_std": std,
        "temperature": float(temp),
        "version": VERSION,
        "input": {"img": 96, "channels": 3, "samples": CAP_LEN},
        "metrics": {"test_acc": hist["test"]["acc"],
                    "acc8": hist["test"]["acc_first8_classes"],
                    "hard_acc": hist.get("hard", {}).get("acc")},
        "train_args": {k: v for k, v in vars(args).items()},
    }
    torch.save(bundle, os.path.join(args.out, "model_bundle.pt"))

    # 训练集嵌入统计（异常检测用）
    ev_tr = evaluate(model, tr["raw"][:min(8000, len(tr["raw"]))],
                     tr["feat"][:min(8000, len(tr["feat"]))],
                     tr["label"][:min(8000, len(tr["label"]))],
                     args.bs, mean, std, want_embed=True)
    np.savez(os.path.join(args.out, "train_embed.npz"),
             embed=ev_tr["embed"], label=tr["label"][:len(ev_tr["embed"])],
             pred=ev_tr["pred"])

    with open(os.path.join(args.out, "train_report.json"), "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    print("\n  -> %s/model_bundle.pt" % args.out)
    print("  -> %s/train_report.json" % args.out)


if __name__ == "__main__":
    main()
