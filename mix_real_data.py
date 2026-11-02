#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mix_real_data.py —— 把板端采集的【真实波形】混入训练数据集

背景：
    现有 wave_weights.bin 用 sim_dds（仿真）训出来，但板子上是真实 AD 模块 +
    真实信号源（量化误差/噪声/带宽限制/失调/触发抖动 都和仿真不同）。
    用真实数据混训，模型才知道「我们的硬件长什么样」。

用法（PC 上跑）：
    # 1. 先生成仿真数据集（用他的脚本，保证格式一致）
    cd ai_delivery/03_源码/common
    python -m dataset_gen --out D:/ubuntu_iso/wave_dataset --train 20000 --val 2000 --test 2000

    # 2. 把板端采的真实数据从板上拷到 PC（目录结构：<real_dir>/<label>.jsonl）
    #    例：D:/ubuntu_iso/real_ds/square.jsonl 等

    # 3. 混入（默认把真实数据放大到占训练集 30%）
    python mix_real_data.py --real D:/ubuntu_iso/real_ds --data D:/ubuntu_iso/wave_dataset --ratio 0.3

    # 4. 训练
    cd ai_delivery/03_源码/train
    python train_waveform.py --data D:/ubuntu_iso/wave_dataset --out D:/ubuntu_iso/wave_model_out

    # 5. 导出权重
    python export_quantized.py --model D:/ubuntu_iso/wave_model_out \
                              --data D:/ubuntu_iso/wave_dataset \
                              --out D:/ubuntu_iso/wave_model_out/quantized_model

    # 6. weights.bin 拷到板上 /home/zynq/wave_weights.bin，重启桌面即可

★ 设计要点：
    ① 预处理必须用他的 preprocess.captures_to_images(mode=...) —— 与推理逐点一致
    ② 类别顺序必须从 dataset/meta.json 读 —— 不能自己猜（他的 CLASSES 有 9 个含 glitch，
       但交付模型是 8 类，dataset 里实际是哪几个要看 meta.json）
    ③ 真实数据量少 ⇒ 按比例 oversample + 可选增强，避免被仿真数据淹没
    ④ 只动 train/val，不动 test（test 保留纯仿真，这样能对比"真实数据训练前后的仿真精度"）
       另外单独写一个 real_test.npz 用于"真实数据上的精度"验收
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


def find_common_dir():
    """定位 ai_delivery/03_源码/common（为了 import preprocess）"""
    cands = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_delivery", "03_源码", "common"),
        r"D:\ubuntu_iso\ai_delivery\03_源码\common",
        "/home/zynq/ai_delivery/03_源码/common",
    ]
    for c in cands:
        if os.path.isdir(c) and os.path.exists(os.path.join(c, "preprocess.py")):
            return c
    raise SystemExit(
        "找不到 ai_delivery/03_源码/common（含 preprocess.py）。\n"
        "请用 --common 指定，或把本脚本放在 D:\\ubuntu_iso 下运行。")


def load_real_jsonl(real_dir):
    """读 <real_dir>/<label>.jsonl，返回 {label: [samples(4096 int)]}"""
    out = {}
    if not os.path.isdir(real_dir):
        raise SystemExit("真实数据目录不存在: %s" % real_dir)
    for fn in sorted(os.listdir(real_dir)):
        if not fn.endswith(".jsonl"):
            continue
        label = fn[:-6]
        arrs = []
        with open(os.path.join(real_dir, fn), encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                s = d.get("samples")
                if not s or len(s) != 4096:
                    print("  [skip] %s 长度不对 (%s)" % (fn, len(s) if s else 0))
                    continue
                arrs.append([int(v) & 0xFF for v in s])   # ★ 训练用 uint8 (0..255)！
        if arrs:
            out[label] = arrs
            print("  %-16s %5d 条" % (label, len(arrs)))
        else:
            print("  %-16s 0 条" % label)
    return out


def main():
    ap = argparse.ArgumentParser(description="把真实数据混入训练数据集")
    ap.add_argument("--real", required=True, help="真实数据目录（<label>.jsonl）")
    ap.add_argument("--data", required=True, help="dataset 目录（含 packed/ 和 meta.json）")
    ap.add_argument("--common", help="preprocess.py 所在目录")
    ap.add_argument("--ratio", type=float, default=0.3,
                    help="真实样本在训练集中的目标占比（默认 0.3 = 30%%）")
    ap.add_argument("--pp", default=None, help="预处理模式 wdens/stft（默认读 meta.json）")
    ap.add_argument("--no-val", action="store_true", help="不往 val 里混（只混 train）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    args = ap.parse_args()

    common = args.common or find_common_dir()
    sys.path.insert(0, common)
    from preprocess import CAP_LEN, IMG, captures_to_images, image_u8_to_int8  # noqa

    print("=" * 66)
    print("真实数据混入训练集")
    print("  preprocess: %s" % common)

    # ---- 读 meta.json 拿类别顺序和预处理模式 ----
    meta_p = os.path.join(args.data, "meta.json")
    if not os.path.exists(meta_p):
        raise SystemExit("找不到 %s（先跑 dataset_gen.py 生成仿真数据集）" % meta_p)
    meta = json.load(open(meta_p, encoding="utf-8"))
    classes = meta.get("classes") or meta.get("extensions", {}).get("classes")
    if not classes:
        raise SystemExit("meta.json 里没有 classes 字段，无法确定类别顺序")
    pp = args.pp or meta.get("pp_mode") or meta.get("extensions", {}).get("pp_mode") or "wdens"
    print("  类别(%d): %s" % (len(classes), classes))
    print("  预处理: %s   图像: %dx%d" % (pp, IMG, IMG))

    # ---- 读真实数据 ----
    print("\n--- 真实数据 ---")
    real = load_real_jsonl(args.real)
    if not real:
        raise SystemExit("真实数据目录里没有有效 jsonl")
    unknown = [k for k in real if k not in classes]
    if unknown:
        print("  ★ 以下真实标签不在 dataset 类别里，将被忽略: %s" % unknown)
        for k in unknown:
            real.pop(k, None)
    if not real:
        raise SystemExit("没有可用的真实数据类别")

    # ---- 加载现有 packed ----
    pk = os.path.join(args.data, "packed")
    def load(split):
        return (np.load(os.path.join(pk, "img_%s.npy" % split)),
                np.load(os.path.join(pk, "label_%s.npy" % split)))
    x_tr, y_tr = load("train")
    x_va, y_va = load("val")
    x_te, y_te = load("test")
    print("\n--- 现有仿真数据集 ---")
    print("  train %s   val %s   test %s" % (x_tr.shape, x_va.shape, x_te.shape))

    # ---- 把真实数据转成图像 ----
    print("\n--- 转换真实数据 -> %dx%d (%s) ---" % (IMG, IMG, pp))
    real_img, real_lab = [], []
    for label, arrs in real.items():
        ci = classes.index(label)
        batch = np.asarray(arrs, dtype=np.uint8)          # (N,4096) 0..255
        imgs = captures_to_images(batch, mode=pp)          # (N,28,28) uint8
        real_img.append(np.asarray(imgs, dtype=np.uint8))
        real_lab.append(np.full(len(arrs), ci, dtype=np.int64))
        print("  %-16s -> %s  label_id=%d" % (label, imgs.shape, ci))
    r_img = np.concatenate(real_img, axis=0)
    r_lab = np.concatenate(real_lab, axis=0)
    print("  真实样本合计: %d" % len(r_img))

    # ---- 计算要混多少（按 target ratio 反推）----
    #   ratio = R / (S + R)  =>  R = ratio * S / (1 - ratio)
    S = len(x_tr)
    R_target = int(round(args.ratio * S / max(1e-6, (1.0 - args.ratio))))
    print("\n--- 混合计划 ---")
    print("  仿真训练集 %d 条，目标真实占比 %.0f%% => 需要真实样本 %d 条" % (
        S, args.ratio * 100, R_target))

    rng = np.random.default_rng(20261021)
    # 按类均衡 oversample
    per_class_target = R_target // len(classes)
    pick = []
    for ci in range(len(classes)):
        idx = np.where(r_lab == ci)[0]
        if len(idx) == 0:
            print("  ★ 警告: 类别 %s 没有真实数据，跳过" % classes[ci])
            continue
        # 先全用一遍，再随机补到 target
        chosen = list(idx)
        while len(chosen) < per_class_target:
            chosen.append(int(rng.choice(idx)))
        pick += chosen[:per_class_target]
    pick = np.asarray(pick, dtype=np.int64)
    rng.shuffle(pick)
    mx = r_img[pick].reshape(-1, 1, IMG, IMG)
    my = r_lab[pick]

    print("  实际混入 train: %d 条（真实）+ %d 条（仿真）" % (len(mx), S))
    print("  新 train: %d 条，真实占比 %.1f%%" % (
        S + len(mx), 100.0 * len(mx) / (S + len(mx))))

    x_new = np.concatenate([x_tr, mx], axis=0)
    y_new = np.concatenate([y_tr, my], axis=0)
    perm = rng.permutation(len(x_new))
    x_new = x_new[perm]
    y_new = y_new[perm]

    # val 也混一点（10%）
    if not args.no_val:
        n_val_real = max(len(classes), int(round(0.1 * len(x_va))))
        vpick = rng.choice(len(r_img), size=min(n_val_real, len(r_img)), replace=False)
        vx = r_img[vpick].reshape(-1, 1, IMG, IMG)
        vy = r_lab[vpick]
        x_va = np.concatenate([x_va, vx], axis=0)
        y_va = np.concatenate([y_va, vy], axis=0)
        p2 = rng.permutation(len(x_va))
        x_va, y_va = x_va[p2], y_va[p2]
        print("  新 val  : %d 条（+%d 真实）" % (len(x_va), len(vx)))

    # 真实数据单独留一份测试集（验收用）
    real_test = {"img": r_img.reshape(-1, 1, IMG, IMG), "label": r_lab,
                 "classes": np.asarray(classes)}

    if args.dry_run:
        print("\n[dry-run] 不写文件")
        return 0

    # ---- 写回 ----
    print("\n--- 写回 %s ---" % pk)
    def save(split, x, y):
        np.save(os.path.join(pk, "img_%s.npy" % split), x.astype(np.uint8))
        np.save(os.path.join(pk, "label_%s.npy" % split), y.astype(np.int64))
        print("  %-6s img%s label%s" % (split, x.shape, y.shape))
    save("train", x_new, y_new)
    save("val", x_va, y_va)
    save("test", x_te, y_te)          # ★ 不动 test（纯仿真，用于对比）

    np.savez_compressed(os.path.join(args.data, "real_test.npz"), **real_test)
    print("  real_test.npz  %s（真实数据验收集）" % (real_test["img"].shape,))

    # 写一个标记，方便训练日志里看出来
    meta["extensions"] = meta.get("extensions") or {}
    meta["extensions"]["real_mix"] = {
        "real_dir": os.path.abspath(args.real),
        "ratio_requested": args.ratio,
        "real_samples_used": int(len(mx)),
        "real_per_class": {classes[ci]: int(np.sum(r_lab == ci))
                           for ci in range(len(classes))},
        "sim_train_before": int(S),
        "train_after": int(len(x_new)),
        "pp_mode": pp,
    }
    json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  meta.json 已更新（extensions.real_mix）")

    print("\n" + "=" * 66)
    print("完成！下一步：")
    print("  cd ai_delivery/03_源码/train")
    print("  python train_waveform.py --data %s --out <输出目录>" % args.data)
    print("  python export_quantized.py --model <输出目录> --data %s --out <输出目录>/quantized_model" % args.data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
