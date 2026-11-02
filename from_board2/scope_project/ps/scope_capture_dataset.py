#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_capture_dataset.py —— 在板上采集【真实波形】并标注，导出训练数据

背景：现在的 wave_weights.bin 是用 sim_dds（仿真 DDS）训出来的，
      但板子上接的是真实 AD 模块 + 真实信号源（有量化误差/噪声/带宽限制/失调）
      ⇒ 用真实数据重训，模型才知道「我们的硬件长什么样」。

用法（板上）：
    # 采 50 帧方波（去把信号发生器调成方波，再运行）
    python3 scope_capture_dataset.py --label square --count 50 --out /home/zynq/real_ds/square.jsonl

    # 8 类全采（每类采完会提示你换波形）
    python3 scope_capture_dataset.py --all --count 40 --outdir /home/zynq/real_ds

    # 只采某几类
    python3 scope_capture_dataset.py --labels sine,square --count 40 --outdir /home/zynq/real_ds

输出格式（JSONL，每行一条）：
    {"samples": [4096 个 int, 0~1023], "label": "square", "ch": 0,
     "fs": 20000000, "dec": 10, "meta": {"vpp_lsb":920,"freq_hz":998.5,"duty_pct":49.9,
     "vmax":420.2,"vmin":-577.5,"triggered":true}, "ts": 1761000000.123}

★ 为什么要 JSONL 而不是 JSON 数组：
   每采一帧就落盘一行，中途Ctrl+C也不会丢掉已采的数据。

★ 增强：--augment 会把每帧额外导出几种「真实退化」变体（增益/偏移/噪声），
   让少量真实数据也能扩出更多训练样本（这是真实数据训练的关键技巧）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
sys.path.insert(0, "/home/zynq")

CLASSES = ["sine", "square", "triangle", "sawtooth",
           "noise", "clipping", "signal_loss", "duty_abnormal"]
CN = {"sine": "正弦波", "square": "方波", "triangle": "三角波", "sawtooth": "锯齿波",
      "noise": "噪声", "clipping": "削顶", "signal_loss": "丢信号", "duty_abnormal": "占空比异常"}


def _meas(samples):
    """从一帧算基本测量值（用于 meta，也用于自动质检）"""
    n = len(samples)
    mn = min(samples)
    mx = max(samples)
    mean = sum(samples) / float(n)
    mids = (mn + mx) / 2.0
    cross = 0
    prev = samples[0] >= mids
    first = None
    last = None
    for i in range(1, n):
        cur = samples[i] >= mids
        if cur != prev:
            cross += 1
            if first is None:
                first = i
            last = i
        prev = cur
    freq = 0.0
    if cross >= 3 and first is not None and last is not None and last > first:
        periods = (cross - 1) / 2.0
        if periods > 0:
            freq = periods * 20000000.0 / 10.0 / (last - first)   # dec=10
    high = sum(1 for v in samples if v >= mids)
    return {
        "vpp_lsb": mx - mn,
        "vmax_lsb": mx,
        "vmin_lsb": mn,
        "mean_lsb": round(mean, 2),
        "freq_hz": round(freq, 1),
        "duty_pct": round(100.0 * high / n, 2),
        "crossings": cross,
    }


def _augment(samples, rnd):
    """真实退化增强：增益抖动 / 直流偏移 / 噪声 / 抽取偏移

    ★ 这不是「造数据」，而是「模拟真实硬件必然存在的差异」：
      不同档位的增益误差、ADC 失调漂移、热噪声、触发点抖动。
    """
    n = len(samples)
    out = []
    # ① 增益抖动 ±8%
    g = 1.0 + rnd.uniform(-0.08, 0.08)
    # ② 直流偏移 ±6 LSB
    off = rnd.uniform(-6.0, 6.0)
    # ③ 噪声 ±2 LSB
    nz = rnd.uniform(0.5, 2.0)
    # ④ 循环移位（模拟触发点抖动）±40 点
    sh = rnd.randint(-40, 40)
    arr = [0] * n
    for i in range(n):
        v = samples[i] * g + off
        if nz > 0:
            v += rnd.gauss(0.0, nz)
        iv = int(round(v))
        if iv < 0: iv = 0
        if iv > 1023: iv = 1023
        arr[(i + sh) % n] = iv
    return arr


def capture_one(hw, npoints=4096):
    """采一帧，返回 (samples, meta)"""
    a1, a2, info = hw.read_frame_locked()
    data = a1 if len(a1) >= npoints else list(a1) * (npoints // max(1, len(a1)) + 1)
    data = [int(v) & 0x3FF for v in data[:npoints]]
    m = _meas(data)
    m.update({
        "triggered": bool(info.get("triggered")),
        "stale": bool(info.get("stale")),
        "dec": int(info.get("dec") or 10),
        "count": int(info.get("count") or len(data)),
    })
    return data, m


def quality_ok(m, label):
    """自动质检：明显不合格的帧直接丢弃（省人工）"""
    if m["vpp_lsb"] < 8:                    # 幅度太小（可能是走错通道/没信号）
        if label not in ("signal_loss", "noise"):
            return False, "幅度太小(%d LSB)" % m["vpp_lsb"]
    if m["vpp_lsb"] > 1010:                 # 满量程乱跳（悬空输入）
        return False, "满量程乱跳(悬空?)"
    if not m["triggered"] and label not in ("noise", "signal_loss"):
        return False, "未触发"
    return True, ""


def main():
    ap = argparse.ArgumentParser(description="采真实波形数据集")
    ap.add_argument("--label", help="单类标签")
    ap.add_argument("--labels", help="逗号分隔多个标签")
    ap.add_argument("--all", action="store_true", help="8 类全采")
    ap.add_argument("--count", type=int, default=40, help="每类帧数（默认 40）")
    ap.add_argument("--gap", type=float, default=0.05, help="两帧间隔秒（默认 0.05）")
    ap.add_argument("--out", help="输出 jsonl 路径（单类模式）")
    ap.add_argument("--outdir", default="/home/zynq/real_ds", help="输出目录")
    ap.add_argument("--ch", type=int, default=0, help="用哪个通道 0/1（默认 0）")
    ap.add_argument("--augment", type=int, default=0, help="每帧额外增强出 N 条")
    ap.add_argument("--no-check", action="store_true", help="关掉自动质检")
    args = ap.parse_args()

    import random
    import scope_dual

    if args.all:
        labels = CLASSES
    elif args.labels:
        labels = [s.strip() for s in args.labels.split(",") if s.strip()]
    elif args.label:
        labels = [args.label]
    else:
        labels = CLASSES
        print("未指定标签，按 8 类全采处理")

    bad = [l for l in labels if l not in CLASSES]
    if bad:
        print("未知标签: %s" % bad)
        print("可选: %s" % CLASSES)
        return 2

    os.makedirs(args.outdir, exist_ok=True)
    hw = scope_dual.ScopeDual()
    rnd = random.Random(int(time.time()))

    total_ok = total_skip = 0
    try:
        for li, label in enumerate(labels):
            path = args.out if (args.out and len(labels) == 1) else \
                   os.path.join(args.outdir, "%s.jsonl" % label)
            print("\n" + "=" * 60)
            print("[%d/%d] 采集 %s（%s）—— 请把信号发生器调成该波形" % (
                li + 1, len(labels), label, CN.get(label, label)))
            print("       目标 %d 帧，输出: %s" % (args.count, path))
            print("=" * 60)
            if li > 0:
                print("  ★ 5 秒后开始，请现在调整信号源…")
                time.sleep(5.0)
            else:
                print("  ★ 3 秒后开始…")
                time.sleep(3.0)

            ok = skip = 0
            fails = {}
            with open(path, "a", encoding="utf-8") as f:
                i = 0
                while i < args.count:
                    data, meta = capture_one(hw)
                    if not args.no_check:
                        good, why = quality_ok(meta, label)
                        if not good:
                            skip += 1
                            fails[why] = fails.get(why, 0) + 1
                            time.sleep(args.gap)
                            continue
                    rec = {"samples": data, "label": label, "ch": args.ch,
                           "fs": 20000000, "dec": meta.get("dec", 10),
                           "meta": meta, "ts": round(time.time(), 3)}
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                    ok += 1
                    # 增强变体
                    for _k in range(max(0, args.augment)):
                        aug = _augment(data, rnd)
                        am = _meas(aug)
                        rec2 = {"samples": aug, "label": label, "ch": args.ch,
                                "fs": 20000000, "dec": meta.get("dec", 10),
                                "meta": am, "ts": round(time.time(), 3),
                                "aug": True}
                        f.write(json.dumps(rec2, separators=(",", ":")) + "\n")
                    i += 1
                    print("  %3d/%d  vpp=%-4d freq=%-7.1f duty=%-6.2f %s" % (
                        i, args.count, meta["vpp_lsb"], meta["freq_hz"],
                        meta["duty_pct"], "(+%d 增强)" % args.augment if args.augment else ""))
                    time.sleep(args.gap)
            total_ok += ok
            total_skip += skip
            print("  ✅ %s: 采到 %d 帧，丢弃 %d 帧 %s" % (
                label, ok, skip, dict(fails) if fails else ""))
    except KeyboardInterrupt:
        print("\n中断（已采的数据都已落盘）")
    finally:
        try:
            hw.close()
        except Exception:
            pass

    print("\n" + "=" * 60)
    print("完成：共采 %d 帧，丢弃 %d 帧" % (total_ok, total_skip))
    print("输出目录: %s" % args.outdir)
    for f in sorted(os.listdir(args.outdir)):
        if f.endswith(".jsonl"):
            p = os.path.join(args.outdir, f)
            n = sum(1 for _ in open(p, encoding="utf-8"))
            print("  %-24s %5d 行  %8.1f KB" % (f, n, os.path.getsize(p) / 1024.0))
    print("\n下一步：把 real_ds 目录拷回 PC，跑 retrain_from_real.py 重训")
    return 0


if __name__ == "__main__":
    sys.exit(main())
