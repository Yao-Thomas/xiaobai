#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loopback_proof.py —— 板载音频链路的**双盲自证**（完全不依赖人耳）

Part 1  数据到底有没有经过 ADC 的增益级？
        改 ADC PGA(0x09) 和 ADC 数字音量(0x10/0x11)，看蜂鸣器响应是否跟着变。
        真 ADC 数据**必须**随数字音量静音(0xC0=−96dB)而消失。

Part 2  放音 → 喇叭 → 空气/结构 → 麦克风 → ADC → DDR 的**频谱矩阵**
        播放若干"无缝"单音（整数个周期，避免循环接缝产生杂波），
        同时录音，然后在所有候选频率上算加窗 Goertzel。
        真回录的话，矩阵**对角线必须占优**（播 990Hz 就只在 990Hz 有峰）。

用法: sudo systemctl stop zynq-audio; sudo python3 loopback_proof.py
"""
import sys
import time
import math
import threading

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
from beep import open_beeper, beep                            # noqa: E402

FS = A.FS
SECS = 0.5


def left_of(data):
    return [s24(int.from_bytes(data[8 * i:8 * i + 4], "little"))
            for i in range(len(data) // 8)]


def right_of(data):
    return [s24(int.from_bytes(data[8 * i + 4:8 * i + 8], "little"))
            for i in range(len(data) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def peak(v):
    return max((abs(x) for x in v), default=0)


def goe(v, f, rate=FS, hann=True):
    """加窗 Goertzel：单频能量（除以 N/2 归一化）。"""
    n = len(v)
    if n < 64:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        if hann:
            x = x * (0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)))
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0)


class Rec(object):
    def __init__(self, cap):
        self.cap = cap

    def grab(self, secs, warm=True):
        """★ 关键纪律：复位 -> 先丢一次暂态 -> 再正式采"""
        if warm:
            self.cap.cfg()
            self.cap.grab(0.08)
        self.cap.cfg()
        d, rate = self.cap.grab(secs)
        return d, rate


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)
    secs = min(SECS, 0.8 * cap.ring / 352800.0)
    rec = Rec(cap)
    i2c = cap.i2c

    # ADC 基础配置（后面只动 0x09 / 0x10 / 0x11）
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x0A, 0x00), (0x0B, 0x02), (0x0C, 0x00),
                 (0x0D, 0x0C)):
        i2c.wr(r, v)

    ADC_BLOCK = ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00))

    def reinit():
        """★ 完整重初始化。实测：0x03 被写成 0xFD(ADC断电) 之后，
        只把 0x03 写回 0x51 是**救不回来**的（RMS 仍为 2.0），
        必须重跑 codec_up() + 整块 ADC 寄存器。"""
        ao.codec_up()
        es8388_set_vol(ao.i2c, 30, 0)
        for r, v in ADC_BLOCK:
            i2c.wr(r, v)
        time.sleep(0.45)

    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    ao.buf.write(0, b"\x00" * ao.ring)
    ao.start()
    time.sleep(0.4)

    print("=" * 78)
    print("loopback_proof  ring=%d  录 %.2fs  满量程=8388607" % (cap.ring, secs))
    print("=" * 78)

    # ---------------- Part 1: 蜂鸣器增益矩阵 ----------------
    fd = open_beeper()
    if fd is None:
        print("没有蜂鸣器设备，跳过 Part 1")
    else:
        print("\n【Part 1】数据有没有经过 ADC 增益级？(声源=板载蜂鸣器)")
        print("%-26s %12s %12s %8s %10s" %
              ("ADC 配置", "静音RMS", "蜂鸣RMS", "比值dB", "蜂鸣峰值"))
        print("-" * 78)
        stop = {"v": False}

        def buzz():
            while not stop["v"]:
                try:
                    beep(1, 70, fd=fd, gap=0.0)
                except Exception:
                    return
                time.sleep(0.015)

        for r03, pga, av, label in ((0x51, 0x66, 0x00, "0x03=51 偏置ON  PGA+18dB ★"),
                                    (0x59, 0x66, 0x00, "0x03=59 偏置OFF PGA+18dB(厂家)"),
                                    (0x51, 0x44, 0x00, "0x03=51 偏置ON  PGA+12dB"),
                                    (0x51, 0x66, 0xC0, "0x03=51 偏置ON  数字-96dB")):
            i2c.wr(0x03, r03)
            i2c.wr(0x09, pga)
            i2c.wr(0x10, av)
            i2c.wr(0x11, av)
            time.sleep(0.30)
            rec.grab(0.05)                         # 丢掉配置后的暂态
            qs, ts = [], []
            for _rep in range(3):
                qs.append(rms(left_of(rec.grab(secs, warm=False)[0])))
                stop["v"] = False
                th = threading.Thread(target=buzz)
                th.start()
                time.sleep(0.12)
                ts.append(rms(left_of(rec.grab(secs, warm=False)[0])))
                stop["v"] = True
                th.join()
            qs.sort(); ts.sort()
            mq, mt = qs[1], ts[1]
            db = 20 * math.log10(max(1e-9, mt) / max(1e-9, mq))
            print("%-26s %12.1f %12.1f %+8.1f  静:%s"
                  % (label, mq, mt, db, " ".join("%.0f" % x for x in qs)))
        try:
            fd.close()
        except Exception:
            pass
        # ★ 必须**完整重初始化**，只写回 0x03 救不回来（实测 RMS 仍 2.0）
        reinit()
        chk, _ = rec.grab(secs)
        print("   [check] 恢复后 0x03=0x%02X  RMS=%.1f  %s"
              % (i2c.rd(0x03), rms(left_of(chk)),
                 "正常" if rms(left_of(chk)) > 3000 else "★仍然死！检查 0x03"))

    # ---------------- Part 2: 放音->麦克风 频谱矩阵 ----------------
    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    ks = [23, 30, 46, 60, 70, 93]
    freqs = [round(k * float(FS) / frames, 2) for k in ks]
    print("\n【Part 2】放音 -> 麦克风 频谱矩阵")
    print("无缝单音（一个缓冲 = %d 帧 = %.1fms，整数周期不产生接缝杂波）"
          % (frames, 1000.0 * frames / FS))
    print("候选频率: " + "  ".join("%.1f" % f for f in freqs))

    # 静音基线
    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.4)
    rec.grab(0.05)
    qd, _ = rec.grab(secs, warm=False)
    ql = left_of(qd)
    base = [goe(ql, f) for f in freqs]
    print("\n静音基线 RMS=%.1f   各频率能量: %s"
          % (rms(ql), " ".join("%.0f" % x for x in base)))

    print("\n%-10s | %s | 判定" % ("播放Hz", " ".join("%9.1f" % f for f in freqs)))
    print("-" * 78)
    rows = []
    for f0 in freqs:
        tone = make_sine(f0, frames=frames, amp=0.9, pack=ao.pack)
        ao.buf.write(0, (tone * 8)[:ao.ring])
        time.sleep(ao.ring / 352800.0 + 0.15)
        rec.grab(0.05)
        d, _ = rec.grab(secs, warm=False)
        l = left_of(d)
        e = [goe(l, f) for f in freqs]
        top = e.index(max(e))
        ok = (top == freqs.index(f0))
        gain = 20 * math.log10(max(1e-9, e[top]) /
                               max(1e-9, base[top]))
        rows.append((f0, e, top, gain, rms(l)))
        print("%-10.1f | %s | %s%s (峰 %.1f, 相对基线 %+.1f dB)"
              % (f0, " ".join("%9.1f" % x for x in e),
                 "★对角线" if ok else "  偏离→%.1f" % freqs[top],
                 "  RMS=%.0f" % rms(l) if False else "", e[top], gain))

    hit = sum(1 for f0, e, top, g, r in rows if top == freqs.index(f0))
    print("\n对角线命中 %d / %d" % (hit, len(freqs)))
    print("结论: " + ("★ 放音链路被麦克风回录证实（频谱矩阵对角线占优）"
                    if hit >= len(freqs) - 1 else
                    "⚠ 对角线不占优，回录证据不足"))

    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
