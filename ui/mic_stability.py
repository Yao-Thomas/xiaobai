#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mic_stability.py —— 找**稳定**的麦克风工作点。

现象: 同一配置连续采集，RMS 在 23000~205000 之间乱跳（差 7~9 倍），
      声学信号完全不可辨。怀疑是 PGA 把悬空的输入节点放大了。

稳定 = 连续多次采集 RMS 抖动小；不稳定 = 悬空/未供电/自激。
对每个配置同时看:
    * 3 次"静音" RMS + 3 次"蜂鸣" RMS
    * 抖动系数 = (max-min)/mean
    * 蜂鸣/静音 比值(dB)

用法: sudo systemctl stop zynq-audio; sudo python3 mic_stability.py
"""
import sys
import time
import math
import threading

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
from beep import open_beeper, beep                            # noqa: E402

FS = A.FS
SECS = 0.4


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x0A, 0x00), (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x0C),
                 (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)

    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)

    def grab():
        cap.cfg()
        cap.grab(0.08)
        cap.cfg()
        d, _ = cap.grab(secs)
        return left(d)

    fd = open_beeper()
    stop = {"v": False}

    def buzz():
        while not stop["v"]:
            try:
                beep(1, 80, fd=fd, gap=0.0)
            except Exception:
                return
            time.sleep(0.01)

    configs = [
        (0x59, 0x66, "0x03=59(偏置关) PGA+18dB  ★当前"),
        (0x51, 0x66, "0x03=51(偏置开) PGA+18dB"),
        (0x59, 0x00, "0x03=59(偏置关) PGA 0dB"),
        (0x51, 0x00, "0x03=51(偏置开) PGA 0dB"),
        (0x51, 0x22, "0x03=51(偏置开) PGA +6dB"),
        (0x51, 0x11, "0x03=51(偏置开) PGA +3dB"),
        (0x01, 0x22, "0x03=01(双声道+偏置开) PGA+6dB"),
    ]

    print("=" * 100)
    print("mic_stability  ring=%d 录%.2fs  满量程=8388607" % (cap.ring, secs))
    print("=" * 100)
    print("%-34s %-30s %-30s %8s %8s" %
          ("配置", "静音 RMS x3", "蜂鸣 RMS x3", "抖动", "蜂鸣dB"))
    print("-" * 100)
    results = []
    for r03, pga, label in configs:
        i2c.wr(0x03, r03)
        i2c.wr(0x09, pga)
        time.sleep(0.30)
        grab()
        offs, ons = [], []
        for k in range(3):
            offs.append(rms(grab()))
            stop["v"] = False
            th = threading.Thread(target=buzz)
            th.start()
            time.sleep(0.12)
            ons.append(rms(grab()))
            stop["v"] = True
            th.join()
        mo = sum(offs) / 3.0
        mn = sum(ons) / 3.0
        jit = (max(offs) - min(offs)) / max(1e-9, mo)
        db = 20 * math.log10(max(1e-9, mn) / max(1e-9, mo))
        print("%-34s %-30s %-30s %8.2f %+8.1f"
              % (label,
                 " ".join("%7.0f" % x for x in offs),
                 " ".join("%7.0f" % x for x in ons), jit, db))
        results.append((label, jit, db, mo, mn))
    print("-" * 100)
    stable = [r for r in results if r[1] < 0.35]
    if stable:
        print("稳定(抖动<0.35)的配置:")
        for lb, j, d, mo, mn in stable:
            print("   %-34s 抖动=%.2f 蜂鸣=%+.1f dB  静音均值=%.0f"
                  % (lb, j, d, mo))
    else:
        print("⚠ 没有任何配置的抖动 < 0.35 —— 麦克风输入级本身不稳定")
    good = [r for r in results if r[2] > 6.0]
    if good:
        print("蜂鸣可辨(>6dB)的配置: " + ", ".join(r[0] for r in good))
    else:
        print("⚠ 没有任何配置能稳定分辨蜂鸣器")

    if fd:
        try:
            fd.close()
        except Exception:
            pass
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
