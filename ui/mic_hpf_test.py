#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mic_hpf_test.py —— 麦克风被低频漂移淹没？分三路查。

观察: 麦克风采集 RMS 在 23000~120000 之间大幅漂移，把声学信号盖住了。
      猜测是 ADC 输入的低频/直流漂移（PGA +18dB 放大了它）。

本脚本对每种配置同时给三个指标:
    raw   : 原始 RMS（受漂移影响）
    ac    : 去掉均值后的 RMS（纯交流）
    hpf   : 一阶高通(截止~200Hz)后的 RMS
    band  : 2~4kHz 能量（蜂鸣器主频段）
并对比 "声源关/声源开"，看**哪个指标能稳定地区分**。

用法: sudo systemctl stop zynq-audio; sudo python3 mic_hpf_test.py
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
SECS = 0.5


def left(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def dc(v):
    return 0.0 if not v else sum(v) / float(len(v))


def ac_rms(v):
    if not v:
        return 0.0
    m = dc(v)
    return math.sqrt(sum((float(x) - m) ** 2 for x in v) / len(v))


def hpf(v, fc=200.0):
    """一阶高通（DC 阻断 + 低切）"""
    if len(v) < 4:
        return v
    a = math.exp(-2.0 * math.pi * fc / FS)
    y = []
    prev_x = float(v[0])
    prev_y = 0.0
    for x in v:
        x = float(x)
        cur = a * (prev_y + x - prev_x)
        y.append(cur)
        prev_x, prev_y = x, cur
    return y


def goe(v, f, rate=FS):
    n = len(v)
    if n < 64:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        x = x * (0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)))
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0)


def band(v, lo=2000, hi=4200, step=100):
    return sum(goe(v, f) for f in range(lo, hi + 1, step))


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x59), (0x09, 0x66), (0x0A, 0x00), (0x0C, 0x00),
                 (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00)):
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

    print("=" * 96)
    print("mic_hpf_test  ring=%d 录%.2fs  满量程=8388607" % (cap.ring, secs))
    print("=" * 96)
    print("%-22s %10s %10s %10s %9s %9s %8s" %
          ("0x0B 配置 / 声源", "raw", "ac", "hpf", "DC", "2-4k", "hpf比值"))

    for b0b, label in ((0x02, "0x0B=0x02(厂家)"),
                       (0x00, "0x0B=0x00"),
                       (0x03, "0x0B=0x03"),
                       (0x01, "0x0B=0x01")):
        i2c.wr(0x0B, b0b)
        time.sleep(0.30)
        grab()
        res = {}
        for tag in ("off", "on"):
            if tag == "on":
                stop["v"] = False
                th = threading.Thread(target=buzz)
                th.start()
                time.sleep(0.15)
            v = grab()
            if tag == "on":
                stop["v"] = True
                th.join()
            h = hpf(v)
            res[tag] = (rms(v), ac_rms(v), rms(h), dc(v), band(v))
        for tag, nm in (("off", "静音"), ("on", "蜂鸣")):
            r0, a0, h0, d0, b0 = res[tag]
            print("%-22s %10.0f %10.0f %10.1f %9.0f %9.0f" %
                  ("%s %s" % (label, nm), r0, a0, h0, d0, b0))
        ho = res["on"][2]
        hf = res["off"][2]
        bo = res["on"][4]
        bf = res["off"][4]
        dbb = 20 * math.log10(max(1e-9, bo) / max(1e-9, bf))
        print("%-22s  -> hpf 蜂鸣/静音 = %.2fx   2-4k 比 = %+.1f dB"
              % ("", ho / max(1e-9, hf), dbb))
        print("-" * 96)

    if fd:
        try:
            fd.close()
        except Exception:
            pass
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
