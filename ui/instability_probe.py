#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instability_probe.py —— 定位"回录电平 30dB 波动"的根因

════════════════════════════════════════════════════════════════════
现象
════════════════════════════════════════════════════════════════════
同一份配置连采多次，峰值在 16355 与 528 之间跳（约 30 dB），
声学信号时有时无。这是 ②③⑤ 能不能可靠的关键。

════════════════════════════════════════════════════════════════════
候选根因（本脚本要逐条排除/坐实）
════════════════════════════════════════════════════════════════════
H1 环形缓冲大小在变
   RawCap 优先要 2048KB，内存碎片化时会退到 1536/1024/…/128KB。
   环越小，能采的时间窗越短（512KB≈1.49s），可能采不到音。
   -> 记录每次的 ring 大小，看低电平是否都对应小环。

H2 物理地址不同 -> DDR bank 不同 -> 耦合噪声不同
   -> 记录 reserve_contig 拿到的物理地址，与 RMS 做相关。

H3 播放环欠载（underrun）：MM2S 的 XFER 不涨，声音中途停
   -> 记录 MM2S XFER 增量，看低电平是否对应 XFER 没动。

H4 采集窗与声音不同步：声音只在前半段/后半段
   -> ★ 把每次采集**切成 8 段**，打印每段 RMS。
      如果整体低但某一段高 -> 是同步问题；
      如果所有段都低           -> 是电平/耦合问题。

H5 寄存器状态残留：每次 cfg() 复位后 ADC 还在建立
   -> 连续采 4 次都不丢弃，看第 1 次是否系统性偏低。

★ 判据仍用**平坦度 > 100**（能区分纯音与噪声，见离线测试台标定）。

用法（必须先停服务，它独占设备）:
    sudo systemctl stop zynq-audio
    sudo python3 /home/zynq/ui/instability_probe.py --trials 12
    sudo systemctl start zynq-audio
"""
import argparse
import json
import math
import sys
import time

sys.path.insert(0, "/home/zynq/ui")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
BASE_REGS = [
    (0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00), (0x03, 0x51),
    (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x02),
    (0x10, 0x00), (0x11, 0x00), (0x18, 0x03), (0x2B, 0x80),
    (0x1A, 0x00), (0x1B, 0x00), (0x27, 0xF8), (0x2A, 0xF8),
]
SEGS = 8


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goe(v, f, rate=FS):
    n = len(v)
    if n < 32:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for i, x in enumerate(v):
        win = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * win + c * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def flatness(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    med = s[len(s) // 2]
    if med <= 0:
        return 1e9 if max(s) > 0 else 0.0
    return max(s) / med


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--freq", type=float, default=990.53)
    ap.add_argument("--secs", type=float, default=0.5)
    ap.add_argument("--amp", type=float, default=0.9)
    ap.add_argument("--out", default="/tmp/instability.json")
    a = ap.parse_args()

    print("=" * 88)
    print("回录电平波动诊断  |  纯音 %.2f Hz  |  %d 次（同配置，不丢弃）"
          % (a.freq, a.trials))
    print("=" * 88)

    cap = RawCap(verbose=True)          # 让它把环形大小打出来
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    i2c = cap.i2c
    for r, v in BASE_REGS:
        i2c.wr(r, v)
    time.sleep(0.3)
    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    # 播放环填满纯音（持续 loop）
    frames = ao.period_bytes // A.BYTES_PER_FRAME
    tone = make_sine(a.freq, frames=frames, amp=a.amp, pack=ao.pack)
    ao.buf.write(0, (tone * 8)[:ao.ring])

    print("环形缓冲: %d 字节 (%.2f 秒)" % (cap.ring, cap.ring / 352800.0))
    print("物理地址等信息见上面 RawCap 的输出\n")

    # MM2S 的 XFER 偏移（audio_pl 里 MM2S=0x100）
    def xfer_mm2s():
        try:
            return mem.rd(A.I2S_BASE, A.MM2S + 0x04)
        except Exception:
            return -1

    def xfer_s2mm():
        try:
            return mem.rd(A.I2S_RX_BASE, A.R2_XFER)
        except Exception:
            return -1

    print("%-5s %-11s %-10s %-11s %-9s %-8s %-6s %s"
          % ("次", "整体RMS", "峰值", "平坦度", "MM2S增", "S2MM增", "环KB",
             "8 段 RMS（看是不是只有某段有声音）"))
    print("-" * 88)

    rows = []
    prev_m, prev_s = xfer_mm2s(), xfer_s2mm()
    for t in range(a.trials):
        cap.cfg()
        d, _ = cap.grab(min(a.secs, 0.8 * cap.ring / 352800.0))
        v = left_of(d)
        m, s = xfer_mm2s(), xfer_s2mm()
        dm, ds = m - prev_m, s - prev_s
        prev_m, prev_s = m, s

        if not v:
            print("%-5d  (无数据)" % (t + 1))
            continue
        R = rms(v)
        P = max(abs(x) for x in v)
        F = flatness([goe(v, a.freq * k) for k in (1, 2, 3)])
        # 分段
        seg = len(v) // SEGS
        segs = [rms(v[i * seg:(i + 1) * seg]) for i in range(SEGS)]
        rows.append({
            "trial": t + 1, "rms": R, "peak": P, "flat": F,
            "d_mm2s": dm, "d_s2mm": ds, "ring": cap.ring,
            "segs": segs,
        })
        print("%-5d %-11.0f %-10d %-11.1f %-9d %-8d %-6d %s"
              % (t + 1, R, P, F, dm, ds, cap.ring // 1024,
                 " ".join("%6.0f" % x for x in segs)))

    ao.buf.write(0, b"\x00" * ao.ring)
    ao.close()
    cap.close()

    # ---------------- 相关性分析 ----------------
    print("\n" + "=" * 88)
    print("相关性分析（判定哪个假设成立）")
    print("=" * 88)
    if len(rows) < 3:
        print("样本太少，无法分析")
        return 1

    rows_sorted = sorted(rows, key=lambda r: r["rms"])
    lo = rows_sorted[:max(1, len(rows) // 4)]
    hi = rows_sorted[-max(1, len(rows) // 4):]

    def avg(rs, k):
        return sum(r[k] for r in rs) / float(len(rs))

    print("低电平组（最低 1/4，n=%d） vs 高电平组（最高 1/4，n=%d)"
          % (len(lo), len(hi)))
    print("  RMS       : %10.0f  vs %10.0f" % (avg(lo, "rms"), avg(hi, "rms")))
    print("  平坦度    : %10.1f  vs %10.1f" % (avg(lo, "flat"), avg(hi, "flat")))
    print("  MM2S 增量 : %10.0f  vs %10.0f" % (avg(lo, "d_mm2s"),
                                               avg(hi, "d_mm2s")))
    print("  S2MM 增量 : %10.0f  vs %10.0f" % (avg(lo, "d_s2mm"),
                                               avg(hi, "d_s2mm")))
    print("  环 KB     : %10.1f  vs %10.1f" % (avg(lo, "ring") / 1024.0,
                                               avg(hi, "ring") / 1024.0))

    # 分段形态：低电平组的"段间差异"
    def seg_ratio(r):
        sr = sorted(r["segs"])
        return sr[-1] / max(1.0, sr[0])
    print()
    print("  段间起伏（最大段/最小段）: 低电平组 %.2f  vs  高电平组 %.2f"
          % (avg(lo, "rms") and sum(seg_ratio(r) for r in lo) / len(lo),
             sum(seg_ratio(r) for r in hi) / len(hi)))

    print()
    print("判读：")
    lf, hf = avg(lo, "flat"), avg(hi, "flat")
    if lf > 100 and hf > 100:
        print("  * 两组都采到了纯音（平坦度都 >100）-> 不是'有没有声音'的问题，"
              "是**电平**在变 -> 指向 H2/H3 之外的耦合或增益波动")
    elif lf < 10 <= hf:
        print("  * 低电平组是噪声、高电平组是纯音 -> **H4/H3**："
              "低电平那几次根本没采到声音（时序或欠载）")
    else:
        print("  * 形态不典型，看上面的分段 RMS 手工判断")

    if abs(avg(lo, "d_mm2s")) < 1000 and abs(avg(hi, "d_mm2s")) > 10000:
        print("  * 低电平组 MM2S 几乎没动 -> **H3 播放环欠载**成立")
    if abs(avg(lo, "ring") - avg(hi, "ring")) > 65536:
        print("  * 两组环形大小明显不同 -> **H1 内存碎片化**成立")

    with open(a.out, "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n明细已存: %s" % a.out)
    print("别忘了: sudo systemctl start zynq-audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
