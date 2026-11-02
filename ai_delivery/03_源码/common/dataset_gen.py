"""
dataset_gen.py —— 接口 ②（数据集格式）的参考实现：生成规范数据集

产出目录（★ 与 07_接口约定单.md 接口 ② 完全一致，另加两个明确标注的扩展）：
    dataset/
    ├─ meta.json                 ★ 规范要求
    ├─ train/  NNNNN.npy + NNNNN.json
    ├─ val/    ...
    ├─ test/   ...
    ├─ raw/                      【扩展】打包的原始 4096 样本缓冲（uint8），
    │                            供示波器方核对、供重跑预处理
    └─ packed/                   【扩展】训练用打包数组（加速 DataLoader）

★ 扩展字段一律在 meta.json 的 "extensions" 里声明，不破坏原格式。

用法：
    python -m dataset_gen --out /data/.../dataset --seed 20261001
    python -m dataset_gen --out ... --train 20000 --val 2000 --test 2000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from preprocess import (CAP_LEN, IMG, captures_to_images,                       # noqa: E402
                        PP_MODES)
from dds_sim import CLASSES, classes_for, make_sample, spec_to_meta     # noqa: E402

DATASET_VERSION = "1.1"
EXTENSIONS = {
    "raw/": "打包的原始采集缓冲 raw_<split>.npy，shape (N,4096) uint8；"
            "便于示波器负责人核对与重跑预处理（接口 ② 未定义，属本项目扩展）",
    "packed/": "打包数组 img_<split>.npy (N,1,28,28) uint8 + label_<split>.npy (N,) int64；"
               "训练用，等价于 train/ 下逐样本 .npy 的拼接",
    "source": "sim_dds = 按板载 DDS 语义仿真生成；hw_scope = 真板采集（示波器负责人产出）",
    "pp_mode": "stft = 对数频率时频图；wdens = 时间×幅度密度图。"
               "★ 因为原始缓冲已全量落盘，换表示不需要重采数据，可用 "
               "scripts/rebuild_images.py 直接重建。",
}


def gen_split(rng: np.random.Generator, n_total: int, split_dir: str,
              raw_dir: str, packed_dir: str, split: str,
              cycles_lo: float, cycles_hi: float, pp: str, cls: list,
              write_per_sample: bool = True, log_every: int = 2000) -> dict:
    """生成一个 split。类别严格均衡（余数随机分配）。cls = 本次使用的类别表。"""
    os.makedirs(split_dir, exist_ok=True)
    n_cls = len(cls)
    per = n_total // n_cls
    counts = [per] * n_cls
    for i in rng.permutation(n_cls)[: (n_total - per * n_cls)]:
        counts[int(i)] += 1

    labels_idx = []
    for ci, c in enumerate(counts):
        labels_idx += [ci] * c
    labels_idx = np.asarray(labels_idx, dtype=np.int64)
    rng.shuffle(labels_idx)

    imgs = np.empty((n_total, 1, IMG, IMG), dtype=np.uint8)
    raws = np.empty((n_total, CAP_LEN), dtype=np.uint8)
    metas = []

    t0 = time.time()
    for i, ci in enumerate(labels_idx):
        label = cls[int(ci)]
        y, spec, info = make_sample(rng, label, cycles_lo=cycles_lo, cycles_hi=cycles_hi)
        raws[i] = y
        metas.append(spec_to_meta(spec, label, info, cls))
        if log_every and (i + 1) % log_every == 0:
            dt = time.time() - t0
            print("    [%s] %6d/%d  %.1fs  (%.0f/s)" % (split, i + 1, n_total, dt, (i + 1) / dt),
                  flush=True)
    imgs[:, 0] = captures_to_images(raws, pp)          # ★ 批量预处理（两种模式）

    if write_per_sample:
        for i in range(n_total):
            stem = "%05d" % i
            np.save(os.path.join(split_dir, stem + ".npy"), imgs[i])
            with open(os.path.join(split_dir, stem + ".json"), "w", encoding="utf-8") as f:
                json.dump(metas[i], f, ensure_ascii=False)

    os.makedirs(raw_dir, exist_ok=True)
    np.save(os.path.join(raw_dir, "raw_%s.npy" % split), raws)

    os.makedirs(packed_dir, exist_ok=True)
    np.save(os.path.join(packed_dir, "img_%s.npy" % split), imgs)
    np.save(os.path.join(packed_dir, "label_%s.npy" % split), labels_idx)

    with open(os.path.join(packed_dir, "meta_%s.json" % split), "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False)

    return {"n": n_total, "class_counts": {cls[i]: int(c) for i, c in enumerate(counts)},
            "seconds": round(time.time() - t0, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--train", type=int, default=20000)
    ap.add_argument("--val", type=int, default=2000)
    ap.add_argument("--test", type=int, default=2000)
    ap.add_argument("--cycles-lo", type=float, default=4.0)
    ap.add_argument("--cycles-hi", type=float, default=64.0)
    ap.add_argument("--no-per-sample", action="store_true",
                    help="只写 packed（大数据集时省时间）")
    ap.add_argument("--with-glitch", action="store_true",
                    help="是否把毛刺(glitch)作为一类；默认不含 —— 见 dds_sim.CLASSES_REQUIRING_PL")
    ap.add_argument("--pp", default="wdens", choices=list(PP_MODES),
                    help="输入表示：wdens=时间×幅度密度图（默认）；stft=对数频率时频图")
    ap.add_argument("--source", default="sim_dds")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    print("=== 生成数据集 -> %s ===" % args.out)
    CLS = classes_for(args.with_glitch)
    print("    类别:", CLS)
    print("    输入表示:", args.pp)
    rng = np.random.default_rng(args.seed)

    stats = {}
    for split, n in (("train", args.train), ("val", args.val), ("test", args.test)):
        if n <= 0:
            continue
        # ★ 各 split 用独立子种子，保证增删样本不影响其他 split 的可复现性
        sub_rng = np.random.default_rng([args.seed, {"train": 1, "val": 2, "test": 3}[split]])
        stats[split] = gen_split(sub_rng, n, os.path.join(args.out, split),
                                 os.path.join(args.out, "raw"),
                                 os.path.join(args.out, "packed"),
                                 split, args.cycles_lo, args.cycles_hi, args.pp, CLS,
                                 write_per_sample=not args.no_per_sample)

    n_total = sum(s["n"] for s in stats.values())
    meta = {
        "dataset_version": DATASET_VERSION,
        "source": args.source,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": args.seed,
        "n_samples": n_total,
        "input_shape": [1, IMG, IMG],
        "input_type": args.pp,
        "input_dtype": "uint8",
        "input_dtype_note": "接口 ② 允许 float32 或 uint8；本项目统一用 uint8(0~255)，"
                            "即 8 位 ADC 的原始码值。送 PL 加速器前按 int8 = u8 - 128 转换"
                            "（唯一转换点，见 quantized_model/README.md）",
        "input_type_note": (
            "wdens = 时间(28列)×幅度(28行)密度图：列内做 8 位码值直方图，"
            "密度取 sqrt 压缩后按样本峰值归一化。行 0 = 顶部 = 高电平。"
            "少周期(K=2~8)时直接呈现波形形状；多周期时退化为各列的幅度分布，"
            "而正弦/三角/锯齿/方波的幅度分布各不相同，仍然可分。"
            "★ 选它而不是 stft 的理由与实测对比见 docs/01_输入表示选型.md。" 
            if args.pp == "wdens" else
            "stft = 对数频率时频图（NFFT=512, hop=132, Hann, bin 1..256 对数分 28 行,"
            "相对峰值固定 60 dB）。需要窗内 ≥2 个周期才分得开谐波，"
            "故少周期工况下信息量不足。"),
        "pp_params": ({"cols": IMG, "rows": IMG, "col_samples": CAP_LEN // IMG,
                       "compression": "sqrt", "normalize": "per-sample peak",
                       "row0": "top = high level"}
                      if args.pp == "wdens" else
                      {"nfft": 512, "hop": 132, "window": "hann", "frames": IMG,
                       "freq_bins": "log-spaced", "rows": IMG, "db_range": 60.0,
                       "normalize": "per-sample peak"}),
        "stft_params": {
            "nfft": 512, "hop": 132, "window": "hann", "frames": IMG,
            "freq_bins": "log-spaced", "rows": IMG, "db_range": 60.0,
            "normalize": "per-sample peak",
            "impl": "src/common/preprocess.py (numpy 与纯 Python 两条路径逐点一致)",
            "capture_len": CAP_LEN,
        },
        "fs_hz": 20000000,
        "dec": 1,
        "fs_note": "fs_hz = 20MHz / dec；dec 逐样本记录在 NNNNN.json 里，"
                   "预处理不需要 fs（频率轴为对数归一化）",
        "cycles_in_capture_range": [args.cycles_lo, args.cycles_hi],
        "classes": CLS,
        "anomaly_classes": [c for c in CLS
                            if c in ("glitch", "clipping", "signal_loss",
                                     "duty_abnormal")],
        "excluded_classes": ([c for c in CLASSES if c not in CLS] or None),
        "excluded_reason": (None if args.with_glitch else
                            "毛刺在 28x28 密度图上不可分（实测只改 2~5/784 个像素，"
                            "二分类召回 0.000）；按团队分工归 PL 硬件检测器负责 —— "
                            "见 docs/01_输入表示选型.md §4"),
        "split": {k: v["n"] for k, v in stats.items()},
        "class_counts": {k: v["class_counts"] for k, v in stats.items()},
        "extensions": EXTENSIONS,
        "generator": "src/common/dataset_gen.py",
    }
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n=== 完成 ===")
    print(json.dumps({k: v["n"] for k, v in stats.items()}, ensure_ascii=False))
    print("meta.json ->", os.path.join(args.out, "meta.json"))


if __name__ == "__main__":
    main()
