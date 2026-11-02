#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""norm_loud.py —— 通用响度归一化（按 RMS，不是峰值）

输入任意 WAV，输出：
  * 峰值压到 -1 dBFS 以内
  * RMS 提到目标响度（默认 -12 dBFS）
  * 多级软限幅，避免硬削顶的失真感
"""
import math
import sys
import wave

import numpy as np


def main():
    src = sys.argv[1]
    dst = sys.argv[2]
    target_db = float(sys.argv[3]) if len(sys.argv) > 3 else -12.0

    with wave.open(src, "rb") as w:
        ch, sw, rate, n = (w.getnchannels(), w.getsampwidth(),
                           w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    v = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if ch == 2:
        mono = v.reshape(-1, 2).mean(axis=1)
    else:
        mono = v

    def rms_db(x):
        r = math.sqrt(float(np.mean(x * x)))
        return 20 * math.log10(max(1e-12, r / 32767.0))

    def pk_db(x):
        return 20 * math.log10(max(1e-12, float(np.max(np.abs(x))) / 32767.0))

    print("  输入: %dHz %dch %.1f 秒" % (rate, ch, n / float(rate)))
    print("        RMS %.1f dBFS   峰值 %.1f dBFS" % (rms_db(mono), pk_db(v)))

    # 先把峰值归一化到 -2 dBFS
    v = v / max(1e-9, float(np.max(np.abs(v)))) * (32767.0 * 10 ** (-2.0 / 20))

    # 再按 RMS 提响度，峰值不许超 -1 dBFS
    want = 32767.0 * (10 ** (target_db / 20.0))
    cur = math.sqrt(float(np.mean(v * v)))
    gain = want / max(1e-9, cur)
    ceil = 32767.0 * 10 ** (-1.0 / 20)
    if float(np.max(np.abs(v))) * gain > ceil:
        gain = ceil / max(1e-9, float(np.max(np.abs(v))))
    v = v * gain

    # 多级软限幅把 RMS 顶上去
    for stage in range(4):
        thr = 32767.0 * (0.88 - stage * 0.10)
        over = np.abs(v) > thr
        if not np.any(over):
            break
        s = np.sign(v[over])
        a = np.abs(v[over])
        v[over] = s * (thr + (32767.0 - thr) *
                       np.tanh((a - thr) / (32767.0 - thr)))
        cur = math.sqrt(float(np.mean(v * v)))
        if cur < want:
            v = v * min(1.25, want / max(1e-9, cur))

    print("  输出: RMS %.1f dBFS   峰值 %.1f dBFS"
          % (rms_db(v), pk_db(v)))

    out = np.clip(np.round(v), -32768, 32767).astype(np.int16)
    with wave.open(dst, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())
    print("  已写 %s (%d 字节)" % (dst, len(out.tobytes())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
