#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_bclk_test.py —— 决定性实验：BCLK = OR(发送器sclk, 接收器sclk)

BD 里 util_vector_logic 是 **或门 (C_OPERATION = "or")**：
        aud_bclk = OR(i2s_transmitter_sclk_out, i2s_receiver_sclk_out)

* 只有一个 sclk 在跑  -> 或门输出 = 那个时钟（干净）✓
* 两个都在跑但相位不同 -> 或门输出几乎恒高 = 不是时钟了 ✗

而 codec 的 LRCK 又**必须**由接收器的 lrclk_out 提供。
所以三种开关组合都试一遍，看哪种能让 ADC 吐出非零数据。
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402


def set_ips(a, rx_on, tx_on):
    """单独控制两个 IP 的 CORE_CTRL"""
    a.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    a.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    time.sleep(0.02)
    if rx_on:
        a.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    if tx_on:
        a.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
    time.sleep(0.02)


def grab(a, secs=0.8):
    a._w(A.R2_CTRL, a._r(A.R2_CTRL) & ~A.CTRL_DMA_EN)
    a._w(A.R2_CTRL, a._r(A.R2_CTRL) | A.CTRL_DMA_EN)
    a._prev = a._r(A.R2_XFER)
    a._total = 0
    a.t0 = time.time()
    t_end = time.time() + secs
    while time.time() < t_end:
        time.sleep(0.25)          # ★ 慢点读, 但用 raw 差值算法
        a.poll_pos()
    _, tot = a.poll_pos()
    dt = time.time() - a.t0
    raw = a.read_ring()
    a._w(A.R2_CTRL, a._r(A.R2_CTRL) & ~A.CTRL_DMA_EN)
    words = [A.struct.unpack_from("<I", raw, i)[0]
             for i in range(0, len(raw) - 3, 4)]
    vals = []
    for w in words:
        v = w & 0xFFFFFF
        if v & 0x800000:
            v -= 1 << 24
        vals.append(v)
    return tot / dt if dt else 0, words, vals


def main():
    a = A.AudioIn(verbose=False)
    try:
        a.codec_adc_up("lin1")
        a.i2s_config()            # 先把两边的分频/声道都配好
        a.fmt_config()
        print("=" * 76)
        print(" BCLK = OR(tx_sclk, rx_sclk)  —— 三种开关组合")
        print("=" * 76)
        for rx_on, tx_on, desc in ((True, True, "两个都开（我们之前的做法）"),
                                   (True, False, "★ 只开接收器"),
                                   (False, True, "只开发送器"),
                                   (False, False, "两个都关")):
            set_ips(a, rx_on, tx_on)
            rate, words, vals = grab(a, 0.8)
            uq = len(set(vals))
            pk = max(abs(v) for v in vals) if vals else 0
            print("\n  rx=%-5s tx=%-5s  %s" % (rx_on, tx_on, desc))
            print("     S2MM %9.1f B/s (%.1f 帧/s)   样本: uniq=%-5d peak=%-8d"
                  % (rate, rate / 8, uq, pk))
            print("     前 8 个字: " + " ".join("0x%08X" % w for w in words[:8]))
    finally:
        a.close()
    print("\n" + "=" * 76)
    print(" 判读：哪一种组合下 样本 uniq/peak 明显变大（不只是 {0,2,3}）")
    print("       哪一种就是让 codec 真正开始转换的组合。")
    print("=" * 76)


if __name__ == "__main__":
    main()
