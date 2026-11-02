"""
build_anomaly.py —— 训练异常检测统计量（马氏距离）+ 在验证集上标定阈值

    python scripts/build_anomaly.py --run runs/v2_full --data data/ds_train

为什么要单独一步：
  · 高斯参数用 **train** 的嵌入拟合；
  · 阈值必须用 **val**（模型没见过）的距离分布标定，否则 p99 会偏小，
    正常样本的误报率会显著高于 1%；
  · 顺手在 OOD（两两混合）上评估检出率，写进 anomaly_report.json。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wave_ai.analyzer import Analyzer  # noqa: E402
from wave_ai.anomaly import (fit_embedding_stats, fit_feature_quantiles,  # noqa: E402
                             mahalanobis, save_stats)
from wave_ai.config import CLASSES  # noqa: E402
from wave_ai.dataset import load_split  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/v2_full")
    ap.add_argument("--data", default="data/ds_train")
    ap.add_argument("--ood", default="data/raw_ood.npy")
    ap.add_argument("--n-val", type=int, default=1200)
    ap.add_argument("--n-ood", type=int, default=400)
    args = ap.parse_args()

    z = np.load(os.path.join(args.run, "train_embed.npz"))
    embed, label = z["embed"], z["label"]
    print("train embeddings:", embed.shape)
    stats = fit_embedding_stats(embed, label)
    print("按类拟合完成：%d 类，维度 %d" % (len(stats["classes"]), stats["dim"]))

    # 规则特征的"本类正常范围"（每类 p99）—— 没有它，固定阈值会把方波
    # 天然很高的 max_res 当成毛刺（实测 43% 误报）
    tr = load_split(args.data, "train")
    feat_q, rule_names = fit_feature_quantiles(tr["feat"][:len(embed)], label, CLASSES)
    stats["feat_q"] = feat_q
    stats["rule_features"] = rule_names
    stats["class_names"] = list(CLASSES)
    print("  规则特征按类 p99 已标定：%s" % ",".join(rule_names))
    print("  train 距离 p50=%.2f p99=%.2f p99.9=%.2f"
          % (stats["train_dist_p50"], stats["train_dist_p99"], stats["train_dist_p999"]))

    a = Analyzer(os.path.join(args.run, "model_bundle.pt"), None)
    va = load_split(args.data, "val")
    n = min(args.n_val, len(va["label"]))
    dv = []
    for i in range(n):
        out = a.infer(va["raw"][i], 20e6, 10, None, want_embed=True)
        dv.append(mahalanobis(out["embed"], stats))
    dv = np.asarray(dv)
    print("val 距离 p50=%.2f p95=%.2f p99=%.2f max=%.2f"
          % (np.median(dv), np.percentile(dv, 95), np.percentile(dv, 99), dv.max()))
    stats["val_dist_p99"] = float(np.percentile(dv, 99))
    stats["val_dist_p95"] = float(np.percentile(dv, 95))
    stats["val_n"] = int(n)

    ood_rep = {}
    if os.path.exists(args.ood):
        ood = np.load(args.ood)
        m = min(args.n_ood, len(ood))
        do = []
        for i in range(m):
            out = a.infer(ood[i], 20e6, 10, None, want_embed=True)
            do.append(mahalanobis(out["embed"], stats))
        do = np.asarray(do)
        thr99 = stats["val_dist_p99"]
        thr95 = stats["val_dist_p95"]
        ood_rep = {
            "n": int(m),
            "ood_dist_p50": float(np.median(do)),
            "detect_rate_at_val_p99": float(np.mean(do > thr99)),
            "detect_rate_at_val_p95": float(np.mean(do > thr95)),
            "val_fp_at_p99": 0.01, "val_fp_at_p95": 0.05,
        }
        print("OOD 距离 p50=%.2f；在 val-p99 阈值 %.2f 上检出 %.1f%%"
              % (np.median(do), thr99, 100 * ood_rep["detect_rate_at_val_p99"]))

    save_stats(stats, os.path.join(args.run, "anomaly_stats.npz"))
    with open(os.path.join(args.run, "anomaly_report.json"), "w", encoding="utf-8") as f:
        json.dump({"fit": "train embeddings", "calibration": "val embeddings",
                   "train_dist_p50": stats["train_dist_p50"],
                   "train_dist_p99": stats["train_dist_p99"],
                   "train_dist_p999": stats["train_dist_p999"],
                   "val_dist_p95": stats["val_dist_p95"],
                   "val_dist_p99": stats["val_dist_p99"],
                   "ood": ood_rep,
                   "note": "阈值取 val 距离 p99；OOD 为训练集未出现过的两类混合波形"},
                  f, ensure_ascii=False, indent=2)
    print("-> %s/anomaly_stats.npz" % args.run)


if __name__ == "__main__":
    main()
