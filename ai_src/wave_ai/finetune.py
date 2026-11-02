"""
finetune.py —— 用板端真实 JSONL 微调（采集清单回来后的第一步）

    python -m wave_ai.finetune --real /path/to/real_ds --model runs/v2_full/model_bundle.pt \
        --out runs/v2_real --epochs 8 --lr 3e-4

输入：目录下若干 `*.jsonl`，每行与采集工具输出一致：
    {"samples":[4096 个 0~1023], "label":"square", "dec":10, "fs":20000000, ...}

做法：
  · 按类分层切 80/20（每类至少 4 条验证样本，太少就全用训练）；
  · **保持原 bundle 的特征标准化参数不变**（否则两套模型不兼容）；
  · 小学习率（默认 3e-4）微调全部参数，focal loss；
  · 真实数据没有端侧概率 ⇒ lp 一律填"1/8 均匀先验 + available=0"，
    与训练时的 dropout 分支一致；
  · 输出新 bundle（格式完全相同，服务直接换 --model 指向它即可）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import torch

from .config import CAP_LEN, CLASSES
from .features import FEATURE_NAMES, extract_features
from .model import WaveFusionNet, count_params
from .representation import to_images, to_model_input
from .train import augment_feat, augment_raw, evaluate, fit_temperature, focal_ce, iter_batches


def load_real(path):
    files = ([path] if path.endswith(".jsonl")
             else glob.glob(os.path.join(path, "**", "*.jsonl"), recursive=True))
    files = sorted(files)
    print("读取 %d 个 JSONL 文件" % len(files))
    raw, label, dec = [], [], []
    skipped = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    skipped["bad_json"] = skipped.get("bad_json", 0) + 1
                    continue
                lab = rec.get("label")
                s = rec.get("samples")
                if lab not in CLASSES or not isinstance(s, list) or len(s) != CAP_LEN:
                    skipped["bad_record"] = skipped.get("bad_record", 0) + 1
                    continue
                raw.append(np.asarray(s, dtype=np.float64))
                label.append(CLASSES.index(lab))
                dec.append(int(rec.get("dec") or 10))
    if skipped:
        print("  跳过:", skipped)
    return (np.clip(np.rint(np.asarray(raw)), 0, 1023).astype(np.uint16),
            np.asarray(label, dtype=np.int64), np.asarray(dec, dtype=np.float64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", required=True)
    ap.add_argument("--model", default="runs/v2_full/model_bundle.pt")
    ap.add_argument("--out", default="runs/v2_real")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    rng = np.random.default_rng(args.seed)
    bundle = torch.load(args.model, map_location="cpu", weights_only=False)
    classes = list(bundle["classes"])
    mean = np.asarray(bundle["feat_mean"], dtype=np.float32)
    std = np.asarray(bundle["feat_std"], dtype=np.float32)

    raw, label, dec = load_real(args.real)
    print("真实样本 %d 条，覆盖 %d 类" % (len(raw), len(set(label.tolist()))))
    if len(raw) < 40:
        print("样本太少（<40），建议先按采集清单每类 100 条；本次仍会跑，但只作流程验证")
    counts = {CLASSES[c]: int((label == c).sum()) for c in sorted(set(label.tolist()))}
    print("  每类条数:", counts)

    # 分层切分
    tr_idx, va_idx = [], []
    for c in sorted(set(label.tolist())):
        idx = np.where(label == c)[0]
        rng.shuffle(idx)
        n_va = max(2, int(round(args.val_ratio * len(idx)))) if len(idx) >= 10 else 0
        va_idx += list(idx[:n_va])
        tr_idx += list(idx[n_va:])
    tr_idx = np.asarray(tr_idx)
    va_idx = np.asarray(va_idx) if va_idx else tr_idx[:0]

    # 特征（真实数据没有端侧概率 → 均匀先验 + available=0）
    feat = np.empty((len(raw), len(FEATURE_NAMES)), dtype=np.float32)
    for i in range(len(raw)):
        fs_eff = 20e6 / max(dec[i], 1.0)
        feat[i], _ = extract_features(raw[i], fs_eff, None)
    print("特征提取完成（lp 一律走「无端侧概率」分支）")

    model = WaveFusionNet(n_classes=len(classes))
    model.load_state_dict(bundle["state_dict"])
    print("参数量 %d；开始微调 %d epoch" % (count_params(model), args.epochs))

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = max(1, args.epochs * max(1, len(tr_idx) // args.bs))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps,
                                                pct_start=0.2)
    best_acc, best_state = -1.0, None
    for ep in range(args.epochs):
        model.train()
        loss_sum, cor, tot = 0.0, 0, 0
        for img, fn, y in iter_batches(raw[tr_idx], feat[tr_idx], label[tr_idx],
                                       args.bs, rng, True, mean, std):
            logits = model(img, fn)
            loss = focal_ce(logits, y, gamma=1.0)
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
        msg = "  ep %2d train %.4f loss %.4f" % (ep + 1, cor / max(tot, 1),
                                                 loss_sum / max(tot, 1))
        if len(va_idx) > 0:
            ev = evaluate(model, raw[va_idx], feat[va_idx], label[va_idx],
                          args.bs, mean, std)
            msg += "  val %.4f" % ev["acc"]
            if ev["acc"] > best_acc:
                best_acc = ev["acc"]
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        print(msg, flush=True)

    if best_state is not None:
        model.load_state_dict(best_state)
    temp = bundle.get("temperature", 1.0)
    if len(va_idx) > 0:
        ev = evaluate(model, raw[va_idx], feat[va_idx], label[va_idx],
                      args.bs, mean, std)
        temp, nll = fit_temperature(ev["logits"], label[va_idx])
        print("val_acc %.4f  temperature %.2f  nll %.4f" % (ev["acc"], temp, nll))

    os.makedirs(args.out, exist_ok=True)
    new = dict(bundle)
    new["state_dict"] = model.state_dict()
    new["temperature"] = float(temp)
    new["finetune"] = {"real_samples": int(len(raw)),
                       "val_n": int(len(va_idx)),
                       "val_acc": None if len(va_idx) == 0 else float(best_acc),
                       "epochs": args.epochs, "lr": args.lr}
    new["metrics"] = dict(bundle.get("metrics", {}))
    if len(va_idx) > 0:
        new["metrics"]["real_val_acc"] = float(best_acc)
    torch.save(new, os.path.join(args.out, "model_bundle.pt"))
    print("->", os.path.join(args.out, "model_bundle.pt"))
    print("   启动：python -m wave_ai.serve --model %s"
          % os.path.join(args.out, "model_bundle.pt"))


if __name__ == "__main__":
    main()
