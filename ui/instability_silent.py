#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instability_silent.py —— **不放音**调查录音电平波动

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
现象：同一份配置连采多次，RMS/峰值能差 15~30 dB（例：602 / 103 / 171 / 145）。
这是 ②③⑤ 能不能可靠的关键，但根因一直没定位。

已排除的：
  * 寄存器配置（每次都重写同一套）
  * 第一次采样的瞬态（已经丢弃第一次）

待查的假设：
  H1  环形缓冲大小在变
      RawCap 优先要 2048KB，内存碎片化时退到 1536/1024/…/128KB。
      环越小能采的时间窗越短。-> 记录每次的 ring 大小，看低电平是否对应小环。
  H2  物理地址不同 -> DDR bank 不同 -> 耦合噪声不同
      -> 记录 reserve_contig 拿到的物理地址。
  H3  采集窗与"某个周期性干扰"不同步
      -> 把每次采集切 8 段，看是整段都低还是只有某段低。
  H4  S2MM 的 XFER 计数异常（采集没真正跑起来）
      -> 记录每次的 XFER 增量。

★ 与原 instability_probe.py 的区别：
   那个会**放音**（用纯音测声学耦合）。
   这个**完全不放音**，只录环境声 —— 所以可以在静音锁生效期间跑。

用法（要停音频服务，它独占设备；但不会出声）:
    sudo systemctl stop zynq-audio
    sudo python3 /home/zynq/ui/instability_silent.py --trials 20
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
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
SEGS = 8
BASE_REGS = [
    (0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00), (0x03, 0x51),
    (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x02),
    (0x10, 0x00), (0x11, 0x00), (0x18, 0x03), (0x2B, 0x80),
    (0x1A, 0x00), (0x1B, 0x00), (0x27, 0xF8), (0x2A, 0xF8),
]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--secs", type=float, default=0.5)
    ap.add_argument("--out", default="/tmp/instability_silent.json")
    a = ap.parse_args()

    print("=" * 88)
    print("录音电平波动调查（**不放音**，只录环境声）")
    print("=" * 88)

    # ★ 必须用 AudioOut 初始化 codec（它才有 codec_up / fmt_config），
    #   但**绝不往播放环里写内容** —— 全程静音。
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.buf.write(0, b"\x00" * ao.ring)          # 播放环全 0 = 完全静音
    cap = RawCap(verbose=True)
    i2c = cap.i2c
    for r, v in BASE_REGS:
        i2c.wr(r, v)
    time.sleep(0.4)

    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    print("环形缓冲: %d 字节 (%.2f 秒)   播放环全 0（静音）"
          % (cap.ring, cap.ring / 352800.0))
    print()

    def xfer():
        try:
            return mem.rd(A.FMT_BASE, A.R2_XFER)
        except Exception:
            return -1

    print("%-5s %-11s %-9s %-8s %-9s %-8s %s"
          % ("次", "整体RMS", "峰值", "环KB", "S2MM增", "非零%", "8 段 RMS"))
    print("-" * 88)

    rows = []
    prev = xfer()
    for t in range(a.trials):
        cap.cfg()
        d, _ = cap.grab(min(a.secs, 0.8 * cap.ring / 352800.0))
        x = xfer()
        dx = x - prev
        prev = x
        v = left_of(d)
        if not v:
            print("%-5d (无数据)" % (t + 1))
            continue
        R = rms(v)
        P = max(abs(x) for x in v)
        nz = sum(1 for x in v if abs(x) > 6) / float(len(v))
        seg = max(1, len(v) // SEGS)
        segs = [rms(v[i * seg:(i + 1) * seg]) for i in range(SEGS)]
        rows.append({"trial": t + 1, "rms": R, "peak": P, "ring": cap.ring,
                     "dx": dx, "nz": nz, "segs": segs})
        print("%-5d %-11.1f %-9d %-8d %-9d %-8.1f %s"
              % (t + 1, R, P, cap.ring // 1024, dx, nz * 100,
                 " ".join("%5.0f" % s for s in segs)))
        time.sleep(0.12)

    # 收尾：保持静音
    ao.buf.write(0, b"\x00" * ao.ring)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    # ---------------- 分析 ----------------
    print("\n" + "=" * 88)
    print("相关性分析")
    print("=" * 88)
    if len(rows) < 4:
        print("样本太少")
        return 1

    rs = sorted(rows, key=lambda r: r["rms"])
    n = max(1, len(rows) // 4)
    lo, hi = rs[:n], rs[-n:]

    def avg(g, k):
        return sum(r[k] for r in g) / float(len(g))

    print("低电平组（最低1/4, n=%d） vs 高电平组（最高1/4, n=%d）" % (len(lo), len(hi)))
    print("  RMS      : %12.1f  vs %12.1f" % (avg(lo, "rms"), avg(hi, "rms")))
    print("  峰值     : %12d  vs %12d" % (avg(lo, "peak"), avg(hi, "peak")))
    print("  环 KB    : %12.1f  vs %12.1f"
          % (avg(lo, "ring") / 1024.0, avg(hi, "ring") / 1024.0))
    print("  S2MM 增量: %12.0f  vs %12.0f" % (avg(lo, "dx"), avg(hi, "dx")))
    print("  非零占比 : %11.1f%% vs %11.1f%%"
          % (avg(lo, "nz") * 100, avg(hi, "nz") * 100))

    spread = max(r["rms"] for r in rows) / max(1e-9, min(r["rms"] for r in rows))
    print()
    print("  RMS 总波动比 = %.1f 倍 = %.1f dB" % (spread, 20 * math.log10(spread)))

    print()
    print("判读:")
    if abs(avg(lo, "ring") - avg(hi, "ring")) > 65536:
        print("  * 两组环大小明显不同 -> **H1 内存碎片化**成立")
    else:
        print("  * 环大小基本一致 -> H1 排除")
    if abs(avg(lo, "dx")) < 1000 <= abs(avg(hi, "dx")):
        print("  * 低电平组 S2MM 几乎没动 -> **H4 采集没跑起来**成立")
    else:
        print("  * S2MM 两组都在动 -> H4 排除")

    # 段内 vs 段间
    def segcv(r):
        segs = r["segs"]
        m = sum(segs) / len(segs)
        if m <= 0:
            return 0.0
        return math.sqrt(sum((s - m) ** 2 for s in segs) / len(segs)) / m
    cv_lo = sum(segcv(r) for r in lo) / len(lo)
    cv_hi = sum(segcv(r) for r in hi) / len(hi)
    print("  段间起伏 CV: 低组 %.2f   高组 %.2f" % (cv_lo, cv_hi))
    print("    （CV 大 = 一次采集里某几段特别响/特别静 = 干扰是阵发的；")
    print("      CV 小 = 整段均匀变化 = 是增益/耦合水平在变）")

    with open(a.out, "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n明细已存: %s" % a.out)
    print("★ 全程没有播放任何声音")
    return 0


if __name__ == "__main__":
    sys.exit(main())
