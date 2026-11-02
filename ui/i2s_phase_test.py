#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i2s_phase_test.py —— 验证 BCLK 相位假设，并找**可重复**的启动时序。

假设：
    aud_bclk = 门(发送器sclk, 接收器sclk)，两个 IP 各自从 MCLK 分频。
    谁先使能、差多少，决定两者相位 φ。OR 的占空比 = 1/2 + φ/T，
    φ→T/2 时 BCLK 退化成**恒定高**（死时钟）→ codec 不移位 → 采集到恒定值。
    两次 AXI 写之间在 Python 里差几百 ns ≈ 0.5~1 个 BCLK 周期 ⇒ 相位随机。

判据：
    "活" = 采集 RMS > 5000（codec 真的在移位，有噪声底）
    "死" = RMS < 100（恒定值，说明 BCLK 是死的）

用法: sudo systemctl stop zynq-audio; sudo python3 i2s_phase_test.py
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
import math                                                    # noqa: E402

RX = A.I2S_RX_BASE
TX = A.I2S_BASE
CTRL = A.I2S_CORE_CTRL
DIV = A.I2S_DIV
TIM = A.I2S_I2STIM
CH0 = A.I2S_CH0
SECS = 0.30
TRIALS = 6


def lrms(d):
    v = [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
         for i in range(len(d) // 8)]
    if not v:
        return 0.0, 0
    return math.sqrt(sum(float(x) * x for x in v) / len(v)), max(abs(x) for x in v)


def main():
    cap = RawCap()
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)

    mem = cap.mem
    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x59), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)

    # 两个 IP 的分频器/声道先都配好
    for base in (RX, TX):
        mem.wr(base, CTRL, 0)
        mem.wr(base, TIM, DIV)
        mem.wr(base, CH0, 1)
    ao.buf.write(0, b"\x00" * ao.ring)

    def grab():
        cap.cfg()
        cap.grab(0.06)
        cap.cfg()
        d, _ = cap.grab(SECS)
        return lrms(d)

    def variant(name):
        """返回该时序的启用动作"""
        if name == "rx然后tx(现在的做法)":
            return lambda: (mem.wr(RX, CTRL, 1), mem.wr(TX, CTRL, 1))
        if name == "tx然后rx":
            return lambda: (mem.wr(TX, CTRL, 1), mem.wr(RX, CTRL, 1))
        if name == "只开rx(tx关闭)":
            return lambda: (mem.wr(RX, CTRL, 0), mem.wr(TX, CTRL, 0),
                            mem.wr(RX, CTRL, 1))
        if name == "只开tx(rx关闭)":
            return lambda: (mem.wr(TX, CTRL, 0), mem.wr(RX, CTRL, 0),
                            mem.wr(TX, CTRL, 1))
        if name == "两个都开-交错写":
            return lambda: (mem.wr(RX, CTRL, 1), mem.wr(TX, CTRL, 1),
                            mem.wr(RX, CTRL, 1), mem.wr(TX, CTRL, 1))
        return lambda: None

    names = ["rx然后tx(现在的做法)", "tx然后rx", "只开rx(tx关闭)",
             "只开tx(rx关闭)", "两个都开-交错写"]
    print("=" * 74)
    print("i2s_phase_test  ring=%d  每格 录%.2fs  判据: RMS>5000=活, <100=死"
          % (cap.ring, SECS))
    print("=" * 74)
    print("%-24s %s" % ("启动时序", " ".join("t%d" % i for i in range(TRIALS))))
    print("-" * 74)
    summary = {}
    for name in names:
        act = variant(name)
        cells = []
        alive = 0
        for t in range(TRIALS):
            mem.wr(RX, CTRL, 0)
            mem.wr(TX, CTRL, 0)
            time.sleep(0.06)
            act()
            time.sleep(0.25)
            r, pk = grab()
            alive += 1 if r > 5000 else 0
            cells.append("%6.0f" % r if r < 1e6 else "%6.2g" % r)
        summary[name] = (alive, TRIALS)
        print("%-24s %s   活 %d/%d" % (name, " ".join(cells), alive, TRIALS))
    print("-" * 74)
    best = max(summary.items(), key=lambda kv: kv[1][0])
    print("最可靠: %s  活 %d/%d" % (best[0], best[1][0], best[1][1]))
    if best[1][0] >= TRIALS - 1:
        print("★ 这个时序可重复 —— 用它")
    else:
        print("⚠ 没有哪种启动时序能稳定复现 => 需要改 bitstream，"
              "把 BCLK 改成只来自一个 IP")

    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
