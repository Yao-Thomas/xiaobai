#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闭环自证：扬声器放音，同时用麦克风录音，看 ADC 数据是否跟着变。

不需要人耳、不需要外接信号源 —— 板载喇叭和板载麦克风在同一块板子上，
放一个响亮的单音，如果 ADC 通路是通的，录到的数据 RMS 会明显抬起来。

用法:
    sudo python3 rec_loop.py                      # 默认 1kHz, lin1 麦克风
    sudo python3 rec_loop.py --freq 1000 --amp 0.9 --blocks 6
    sudo python3 rec_loop.py --sweep-in           # 依次试各个 ADC 输入通道
    sudo python3 rec_loop.py --bias               # 打开 mic bias (0x03 bit3=0)
    sudo python3 rec_loop.py --vol 33             # 输出音量最大
"""
import sys
import time
import math
import array

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioIn, AudioOut, make_sine, es8388_set_vol   # noqa: E402


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


def capture(ai, secs, poll=0.010):
    """按 DMA 写指针增量取数据，避开环形回绕。"""
    ring = ai.ring
    prev = ai.raw_xfer() % ring
    buf = bytearray()
    t_end = time.time() + secs
    while time.time() < t_end:
        pos = ai.raw_xfer() % ring
        if pos != prev:
            if pos > prev:
                buf += ai.buf.read(prev, pos - prev)
            else:
                buf += ai.buf.read(prev, ring - prev)
                buf += ai.buf.read(0, pos)
            prev = pos
        time.sleep(poll)
    return bytes(buf)


def lr(data):
    """8 字节一帧 -> (L 列表, R 列表)，24bit 右对齐有符号。"""
    ls, rs = [], []
    n = len(data) // 8
    for i in range(n):
        l = int.from_bytes(data[8 * i:8 * i + 4], "little") & 0xFFFFFF
        r = int.from_bytes(data[8 * i + 4:8 * i + 8], "little") & 0xFFFFFF
        ls.append(l - 0x1000000 if l & 0x800000 else l)
        rs.append(r - 0x1000000 if r & 0x800000 else r)
    return ls, rs


def rms(v):
    if not v:
        return 0.0
    return math.sqrt(sum(float(x) * x for x in v) / len(v))


def goertzel(v, freq, fs=A.FS):
    if len(v) < 64:
        return 0.0
    w = 2.0 * math.pi * freq / fs
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in v:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) / (len(v) / 2.0)


def peak_freq(v, lo=200, hi=6000, step=50, fs=A.FS):
    best, bf = -1.0, 0
    f = lo
    while f <= hi:
        g = goertzel(v, f, fs)
        if g > best:
            best, bf = g, f
        f += step
    return bf, best


def run(ai, ao, freq, amp, blocks, tone_bytes, sil_bytes, label, secs=0.40):
    # 环形缓冲要整圈换掉才听得到新内容：ring/352800 秒，再多等 80ms
    settle = ao.ring / 352800.0 + 0.08
    print("\n===== %s =====" % label)
    print("(环形 %dB = %.0fms，每块先等 %.0fms 让新内容播出来)"
          % (ao.ring, 1000.0 * ao.ring / 352800.0, 1000 * settle))
    print("块  时长   放音   L_RMS      R_RMS      @%dHz(L)   峰值Hz" % freq)
    res = []
    for k in range(blocks):
        on = (k % 2 == 0)
        ao.buf.write(0, (tone_bytes if on else sil_bytes)[:ao.ring])
        time.sleep(settle)                  # 让 DMA 把新内容播出去
        d = capture(ai, secs)
        ls, rs = lr(d)
        rl, rr = rms(ls), rms(rs)
        g = goertzel(ls, freq)
        pf, pg = peak_freq(ls) if rl > 1.0 else (0, 0.0)
        print(" %d  %5.2fs  %s   %8.1f  %8.1f  %9.1f   %5d (%.0f)"
              % (k, secs, "ON " if on else "off", rl, rr, g, pf, pg))
        res.append((on, rl, g, pf))
    on_r = [r[1] for r in res if r[0]]
    off_r = [r[1] for r in res if not r[0]]
    on_g = [r[2] for r in res if r[0]]
    off_g = [r[2] for r in res if not r[0]]
    if on_r and off_r:
        mo = sum(on_r) / len(on_r)
        mf = sum(off_r) / len(off_r)
        print(" -> L_RMS  放音 %.1f / 静音 %.1f = %.2fx" % (mo, mf, mo / max(1e-9, mf)))
    if on_g and off_g:
        go = sum(on_g) / len(on_g)
        gf = sum(off_g) / len(off_g)
        db = 20 * math.log10(max(1e-9, go) / max(1e-9, gf))
        flag = "  <== 麦克风听到了!" if db > 6 else ""
        print(" -> @%.0fHz 放音 %.1f / 静音 %.1f = %.2fx (%+.1f dB)%s"
              % (freq, go, gf, go / max(1e-9, gf), db, flag))
    return res


def main():
    freq = arg("--freq", 1000.0, float)
    amp = arg("--amp", 0.9, float)
    blocks = arg("--blocks", 6, int)
    vol = arg("--vol", 30, int)
    sweep = "--sweep-in" in sys.argv
    bias = "--bias" in sys.argv
    ins = ["lin1", "mic1", "mic2", "line"] if sweep else [arg("--in", "lin1")]

    ai = AudioIn()
    ao = AudioOut()
    ao.codec_up()                                  # 完整 ES8388 初始化（含 DAC）
    ao.i2s_config()                                # 收发都配
    ai.fmt_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, vol, 0)                 # 输出最大 + DAC 数字 0dB

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=amp, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    sil_bytes = b"\x00" * ao.ring

    ai.start()
    ao.start()
    print("[loop] 放音 %.0fHz amp=%.2f vol=%d  录音 ring=%dB  采样率=%d"
          % (freq, amp, vol, ai.ring, A.FS))

    try:
        for name in ins:
            ai.codec_adc_up(adc_in=name)
            if bias:
                v = ai.i2c.rd(0x03)
                ai.i2c.wr(0x03, v & ~0x08)         # PdnMICB = 0 -> 打开 mic 偏置
                print("[bias] 0x03: 0x%02X -> 0x%02X (mic bias ON)"
                      % (v, ai.i2c.rd(0x03)))
            run(ai, ao, freq, amp, blocks, tone_bytes, sil_bytes,
                "ADC 输入 = %s (0x0A=0x%02X) 0x03=0x%02X"
                % (name, ai.i2c.rd(0x0A), ai.i2c.rd(0x03)))
    finally:
        ao.buf.write(0, sil_bytes)
        time.sleep(0.1)
        ao.stop()
        ai.stop()
        ai.close()
        ao.close()


if __name__ == "__main__":
    main()
