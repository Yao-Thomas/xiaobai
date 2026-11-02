#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_dist.py —— 数一数录到的字里各值出现多少次

判据（决定性）：
  A) 如果录到的是【AES 子帧】：
       低 4 位 = 前导码  Z=0001(0x1) / X=0010(0x2) / Y=0011(0x3)
       规律：Z 每 192 个子帧出现一次 -> 值 0x1 约占 1/192 ≈ 0.52%
             X / Y 交替，各约一半
  B) 如果录到的是【真实样本】（ADC 在转换、输入静音）：
       样本值会是一个连续分布（噪声±几个 LSB），
       不会出现"只有 1/2/3 三个离散值"这种数字规律

所以：出现 0x1 且比例≈0.52% -> 是 AES 前导码 -> ASDOUT 没数据
      没出现 0x1，值是个小范围分布 -> ADC 在工作，只是没信号
"""
import sys
import time
from collections import Counter

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402


def main():
    adc_in = sys.argv[1] if len(sys.argv) > 1 else "lin1"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    a = A.AudioIn(verbose=False)
    try:
        a.codec_adc_up(adc_in)
        a.i2s_config()
        a.fmt_config()
        a.start()
        # ★ 必须高频轮询：环形缓冲 32768 字节，352800B/s 下 93ms 就回绕一圈
        t_end = time.time() + secs
        while time.time() < t_end:
            a.poll_pos()
            time.sleep(0.02)
        raw = a.read_ring()
        _, tot = a.poll_pos()
        dt = time.time() - a.t0
        a.stop()
    finally:
        pass

    words = [A.struct.unpack_from("<I", raw, i)[0]
             for i in range(0, len(raw) - 3, 4)]
    print("=" * 74)
    print(" ADC输入=%s  录 %.1f 秒  环形缓冲 %d 字节" % (adc_in, secs, a.ring))
    print(" XFER 累计 %d 字节 / %.2f s = %.1f B/s (期望 352800)"
          % (tot, dt, tot / dt if dt else 0))
    print("=" * 74)
    print(" 这次抓到 %d 个 32bit 字" % len(words))

    c_lo = Counter(w & 0xFFFFFF for w in words)
    c_mid = Counter((w >> 4) & 0xFFFFFF for w in words)
    c_full = Counter(words)

    def show(title, cnt, total):
        print("\n--- %s （共 %d 种取值）" % (title, len(cnt)))
        for v, n in cnt.most_common(12):
            print("     值 %-10d 出现 %-7d 次  占 %.4f%%" % (v, n, 100.0 * n / total))

    show("整个 32bit 字", c_full, len(words))
    show("低 24 位 (w & 0xFFFFFF)", c_lo, len(words))
    show("中 24 位 ((w>>4) & 0xFFFFFF)", c_mid, len(words))

    n1 = c_full.get(0x00000001, 0) + c_full.get(0x00000011, 0)
    print("\n" + "=" * 74)
    print(" 关键判据：值为 1（Z 前导码）出现 %d 次，理论应有 %.0f 次（1/192）"
          % (n1, len(words) / 192.0))
    if len(c_full) <= 6 and n1 > 0:
        print(" >>> 只有极少数几个离散值，且 1 按 1/192 出现")
        print("     => 录到的是 **AES 前导码**，ADC 没送数据（ASDOUT 恒 0）")
    elif len(c_full) > 8:
        print(" >>> 取值是个连续分布 => **ADC 在真的转换**，只是输入没信号")
    else:
        print(" >>> 不好判断，看上面的分布")
    print("=" * 74)
    a.close()


if __name__ == "__main__":
    main()
