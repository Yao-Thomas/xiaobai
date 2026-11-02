#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原始字节取样：S2MM 环形缓冲里到底写进了什么。

用法:
    sudo python3 rec_raw.py                     # 正常配置（lin1 麦克风）
    sudo python3 rec_raw.py --in mic1
    sudo python3 rec_raw.py --off               # 控制组：codec 全部断电
    sudo python3 rec_raw.py --dw 24             # 不旁路 aes_dec (位宽=24)
    sudo python3 rec_raw.py --secs 0.4
"""
import sys
import time
import collections

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioIn                                  # noqa: E402


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


def hexdump(b, base=0, per=16, limit=128):
    out = []
    for o in range(0, min(len(b), limit), per):
        chunk = b[o:o + per]
        hx = " ".join("%02X" % c for c in chunk)
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        out.append("  %08X  %-*s |%s|" % (base + o, per * 3 - 1, hx, asc))
    return "\n".join(out)


def words_le(b, n=None):
    out = []
    m = len(b) // 4 if n is None else n
    for i in range(m):
        v = b[4 * i] | (b[4 * i + 1] << 8) | (b[4 * i + 2] << 16) | (b[4 * i + 3] << 24)
        out.append(v)
    return out


def s24(v):
    v &= 0xFFFFFF
    return v - 0x1000000 if v & 0x800000 else v


def main():
    adc_in = arg("--in", "lin1")
    secs = arg("--secs", 0.4, float)
    dw = arg("--dw", 32, int)
    off = "--off" in sys.argv
    nbytes = arg("--n", 8192, int)

    ai = AudioIn(dw=dw)
    ai.i2s_config()
    ai.codec_adc_up(adc_in=adc_in)
    if off:
        ai.i2c.wr(0x02, 0xC3)      # 数字全断电
        ai.i2c.wr(0x03, 0xFC)      # 模拟全断电
        ai.i2c.wr(0x08, 0x00)
        print("[cfg] 控制组：codec 全部断电 0x02=0x%02X 0x03=0x%02X"
              % (ai.i2c.rd(0x02), ai.i2c.rd(0x03)))
    ai.fmt_config()
    ai.start()
    time.sleep(secs)
    x1 = ai.raw_xfer()
    time.sleep(0.2)
    x2 = ai.raw_xfer()
    ai.stop()

    ring = ai.ring
    d = x2 - x1
    if d < 0:
        d += ring
    rate = d / 0.2
    print("[rate] XFER %.0f -> %.0f  Δ=%d B / 0.2s => %.0f B/s  (%.1f frames/s)"
          % (x1, x2, d, rate, rate / A.BYTES_PER_FRAME))

    data = ai.read_ring()
    print("[ring] %d B, 唯一字节数=%d" % (len(data), len(set(data))))

    hist = collections.Counter(data)
    print("[hist] 出现最多的 12 个字节值:")
    for v, c in hist.most_common(12):
        print("   0x%02X : %7d  %6.2f%%" % (v, c, 100.0 * c / len(data)))

    nz = [c for v, c in hist.items() if v != 0]
    print("[hist] 非零字节总数 = %d / %d (%.3f%%)"
          % (sum(nz), len(data), 100.0 * sum(nz) / len(data)))

    print("\n[head] 前 128 字节 (按 32bit 字对齐):")
    print(hexdump(data[:128]))

    w = words_le(data[:256])
    print("\n[head] 前 32 个 LE 32bit 字 -> 低24位有符号值:")
    for i in range(0, 32, 8):
        print("   w%-3d " % i + " ".join("%10d" % s24(v) for v in w[i:i + 8]))
    print("   raw  " + " ".join("%08X" % v for v in w[:8]))

    # 按 8 字节一帧看：ch0/ch1 是否相同、是否互为相反
    print("\n[frame] 前 12 帧 (每帧 8B = L,R):")
    for i in range(12):
        fr = data[8 * i:8 * i + 8]
        if len(fr) < 8:
            break
        l = s24(int.from_bytes(fr[0:4], "little"))
        r = s24(int.from_bytes(fr[4:8], "little"))
        print("   f%-3d L=%-10d R=%-10d   L!=R:%s" % (i, l, r, l != r))

    # 是否有 0x5A ('Z') 之类的 AES 前导
    print("\n[aes] 0x5A 出现 %d 次, 0xF 高半字节字节数=%d"
          % (hist.get(0x5A, 0), sum(c for v, c in hist.items() if v >> 4 == 0xF)))
    print("[aes] 期望: 若真是 AES 每 192 帧 1 个 Z -> ring %d B = %d 帧 -> ~%.1f 个"
          % (len(data), len(data) // 8, len(data) / 8.0 / 192))

    ai.close()


if __name__ == "__main__":
    main()
