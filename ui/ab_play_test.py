#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_play_test.py —— 用麦克风当裁判，A/B 对比两种播放方式

背景：`POST /play {"tone":...}` 响得吓人，`{"file":...}` 一点声没有。
      数字侧寄存器、DMA、I2S 都验证过是活的。

这个脚本把变量降到最少，直接对比：

  A  文件数据 -> **流式分块**写（服务新代码的做法）
  B  文件数据 -> **一次性写满环**（能出声的 play_tone 的做法）

  C  纯音       -> 一次性写满环（对照组，确认硬件确实响）

并且**跳过文件开头的静音段**，排除淡入。

每一步都用麦克风测同一个频点的能量，用数据说话。
"""
import math
import struct
import sys
import time
import wave

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
F0 = 990.5
BYTES_PER_FRAME = 8


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goe(v, f, rate=FS):
    n = len(v)
    if n < 64:
        return 0.0
    c = 2.0 * math.cos(2.0 * math.pi * f / rate)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * w + c * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def pack16(samples, pack="rj"):
    """int16 -> 8字节/帧字节流（和服务同样的约定）"""
    out = bytearray()
    for v in samples:
        if pack == "lj":
            out += struct.pack("<I", (v * 256) & 0xFFFFFFFF)
        else:
            out += struct.pack("<I", (v * 256) & 0xFFFFFF)
    return bytes(out)


def main():
    # ---- 读文件，跳过开头静音 ----
    p = "/home/zynq/Music/03_小星星.wav"
    w = wave.open(p, "rb")
    ch, r = w.getnchannels(), w.getframerate()
    raw = w.readframes(w.getnframes())
    w.close()
    s16 = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    # 找第一个幅度 >1000 的位置（跳过淡入）
    start = 0
    for i in range(0, len(s16)):
        if abs(s16[i]) > 1000:
            start = i - (i % ch)
            break
    print("  文件: %s  %d Hz %d声道" % (p, r, ch))
    print("  跳过开头静音: 从样本 %d 开始 (%.3f 秒)"
          % (start, start / float(r) / ch))
    seg = s16[start:start + int(0.5 * r) * ch]      # 取 0.5 秒
    pk = max(abs(x) for x in seg)
    g = (0.9 * 32767) / float(pk) if pk else 1.0
    g = min(g, 12.0)
    seg = [int(x * g) for x in seg]
    print("  取 0.5 秒, 归一化 %.2f 倍 -> 峰值 %d" % (g, max(abs(x) for x in seg)))

    # ---- 初始化（★ 全都要）----
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)
    ao.start()

    cap = RawCap(verbose=False)
    i2c = cap.i2c
    for reg, val in [(0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                     (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                     (0x0C, 0x00), (0x0D, 0x02), (0x10, 0x00), (0x11, 0x00),
                     (0x18, 0x03), (0x2B, 0x80)]:
        i2c.wr(reg, val)
    time.sleep(0.4)
    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    ring = ao.ring
    silence = b"\x00" * ring
    frames_per_ring = ring // BYTES_PER_FRAME

    def grab(secs=0.4):
        cap.cfg()
        d, _ = cap.grab(secs)
        return left_of(d)

    def measure(label, write_fn, secs=0.5):
        write_fn()
        time.sleep(0.15)
        v = grab(secs)
        return rms(v), max(abs(x) for x in v) if v else 0

    print()
    print("=" * 88)
    print("  %-30s %-12s %-12s %s" % ("方式", "总RMS", "峰值", "990Hz能量"))
    print("=" * 88)

    # ---- 基线 ----
    def w_sil():
        ao.buf.write(0, silence)
    R, P = measure("基线(静音)", w_sil)
    base = (R, P, goe(grab(0.4), F0))
    print("  %-30s %-12.0f %-12d %.3g" % ("基线(静音)", R, P, base[2]))

    # ---- C 纯音，一次性写满（对照组）----
    def w_tone():
        tone = (make_sine(990.5, frames=frames_per_ring, amp=0.9,
                          pack=ao.pack))
        ao.buf.write(0, tone[:ring])
    R, P = measure("C 纯音(一次性写满)", w_tone)
    E = goe(grab(0.4), F0)
    print("  %-30s %-12.0f %-12d %.3g" % ("C 纯音(一次性写满)", R, P, E))
    ao.buf.write(0, silence)
    time.sleep(0.3)

    # ---- B 文件数据，一次性写满（跳静音后 0.186 秒）----
    pcm = pack16(seg)
    def w_once():
        blk = pcm[:ring]
        if len(blk) < ring:
            blk = blk + b"\x00" * (ring - len(blk))
        ao.buf.write(0, blk)
    R, P = measure("B 文件(一次性写满)", w_once)
    E = goe(grab(0.4), F0)
    print("  %-30s %-12.0f %-12d %.3g" % ("B 文件(一次性写满)", R, P, E))
    ao.buf.write(0, silence)
    time.sleep(0.3)

    # ---- A 文件数据，流式分块 ----
    def w_stream():
        total = len(pcm)
        pos = 0
        while pos < total:
            blk = pcm[pos:pos + ring]
            if len(blk) < ring:
                blk = blk + b"\x00" * (ring - len(blk))
            ao.buf.write(0, blk)
            time.sleep(0.171)
            pos += ring
    R, P = measure("A 文件(流式分块)", w_stream)
    E = goe(grab(0.4), F0)
    print("  %-30s %-12.0f %-12d %.3g" % ("A 文件(流式分块)", R, P, E))

    ao.buf.write(0, silence)
    time.sleep(0.3)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 0)
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 0)
    try:
        ao.close()
    except Exception:
        pass
    cap.close()

    print()
    print("★ 判读：总RMS 明显高于基线的，就是真出声了。")
    print("        C 是已知能出声的对照组。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
