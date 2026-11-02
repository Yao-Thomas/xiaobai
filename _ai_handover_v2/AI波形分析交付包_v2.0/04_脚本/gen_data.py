"""
gen_data.py —— 一次性生成全部数据（训练/验证/测试/困难域/未知异常）

    python scripts/gen_data.py --out data/ds_train --hard data/ds_hard \
        --train 24000 --val 3000 --test 3000 --hard-n 3000 --ood 600
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wave_ai.config import CLASSES  # noqa: E402
from wave_ai.dataset import build, build_split, make_ood  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ds_train")
    ap.add_argument("--hard", default="data/ds_hard")
    ap.add_argument("--train", type=int, default=24000)
    ap.add_argument("--val", type=int, default=3000)
    ap.add_argument("--test", type=int, default=3000)
    ap.add_argument("--hard-n", type=int, default=3000)
    ap.add_argument("--ood", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()

    build(args.out, args.train, args.val, args.test, args.seed)

    # ---- 困难域（只作测试：更差 SNR / 更窄带宽 / 更大增益误差）----
    print("\n=== 困难域测试集 -> %s ===" % args.hard)
    st = build_split(args.hard, "test", args.hard_n, args.seed + 1, domain="hard")
    with open(os.path.join(args.hard, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "sim_hw_10bit", "domain": "hard",
                   "classes": CLASSES, "split": {"test": st["n"]},
                   "note": "噪声 16~32 LSB、带宽 0.30~0.55 Nyquist、增益 ±20%、"
                           "偏置 ±45 LSB —— 比训练域明显更差，用于估计域偏移掉点"},
                  f, ensure_ascii=False, indent=2)

    # ---- 未知异常（训练集里没有的两两混合）----
    print("\n=== 未知异常混合集 -> %s ===" % os.path.dirname(args.out))
    raw, pairs = make_ood(args.ood, seed=args.seed + 2)
    np.save(os.path.join(os.path.dirname(args.out), "raw_ood.npy"), raw)
    with open(os.path.join(os.path.dirname(args.out), "ood_pairs.json"), "w",
              encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False)
    print("  OOD: %d 条" % len(raw))
    print("\n全部数据生成完成。")


if __name__ == "__main__":
    main()
