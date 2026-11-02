#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_ratio_sweep.py —— 扫描 ES8388 的 ADC 采样率比例码值 (reg 0x0D)

背景：厂家初始化表把 0x0D 写成 0x0C，但按他们自己的 coeff_div 表，
      码值 0x0C = 比例 2304（那是 18.432MHz@8kHz 用的），
      我们 MCLK=16.9344MHz@44.1kHz 应该是 **0x03（比例 384）**。
      DAC 那边 (0x18) 写的就是 0x03，只有 ADC 抄错了。

做法：每个码值录两小段（静音 / 蜂鸣器响），比 RMS，谁响谁对。
"""
import math
import sys
import threading
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402
import beep as B                # noqa: E402


def rms_rj(words):
    """按右对齐低 24 位取样本（I2S 接收器给的是 AES 子帧，样本在 [27:4]）"""
    if not words:
        return 0.0, 0
    s = 0
    peak = 0
    n = 0
    for w in words:
        v = (w >> 4) & 0xFFFFFF          # ★ 样本在 [27:4]（前面看到前导码在低 4 位）
        if v & 0x800000:
            v -= 1 << 24
        s += v * v
        peak = max(peak, abs(v))
        n += 1
    return math.sqrt(s / float(n)), peak


def capture(a, secs):
    a.start()
    t_end = time.time() + secs
    while time.time() < t_end:
        a.poll_pos()
        time.sleep(0.03)
    raw = a.read_ring()
    a.stop()
    return [A.struct.unpack_from("<I", raw, i)[0]
            for i in range(0, len(raw) - 3, 4)]


def main():
    codes = [int(x, 16) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                                  else ["0", "1", "2", "3", "4", "5", "6", "7",
                                        "8", "9", "a", "b", "c", "d"])]
    adc_in = sys.argv[2] if len(sys.argv) > 2 else "lin1"

    print("=" * 76)
    print(" ADC 比例码值扫描   reg 0x0D   (ADC输入=%s)" % adc_in)
    print(" 每个码值：先录静音，再让蜂鸣器响着录 —— 谁让 RMS 变大谁就是对的")
    print("=" * 76)
    print(" %-6s %-10s %-22s %-22s" % ("码值", "比例", "静音 RMS/峰值", "蜂鸣器 RMS/峰值"))
    print("-" * 76)

    RATIO = {0: 128, 1: 192, 2: 256, 3: 384, 4: 512, 5: 576, 6: 768,
             7: 1024, 8: 1152, 9: 1408, 10: 1536, 11: 2112, 12: 2304}

    best = None
    for c in codes:
        a = A.AudioIn(verbose=False)
        try:
            a.codec_adc_up(adc_in)
            a.i2c.wr(0x0D, c)            # ★ 覆盖 ADC 比例
            a.i2s_config()
            a.fmt_config()

            q = rms_rj(capture(a, 0.7))
            th = threading.Thread(target=lambda: B.beep(1, 700), daemon=True)
            th.start()
            time.sleep(0.03)
            l = rms_rj(capture(a, 0.7))
            th.join(timeout=2)

            gain = (l[0] / q[0]) if q[0] > 0.01 else (999.0 if l[0] > 0.01 else 0.0)
            mark = ""
            if best is None or l[0] > best[1]:
                best = (c, l[0])
                mark = "  <== 目前最好"
            print(" 0x%02X    %-10s %-22s %-22s%s"
                  % (c, RATIO.get(c, "?"),
                     "%.1f / %d" % q, "%.1f / %d" % l, mark))
        except Exception as e:
            print(" 0x%02X    !! %s: %s" % (c, type(e).__name__, e))
        finally:
            a.close()
        time.sleep(0.15)

    print("-" * 76)
    if best:
        print(" >>> 最好的码值 = 0x%02X (比例 %s)，蜂鸣器时 RMS=%.1f"
              % (best[0], RATIO.get(best[0], "?"), best[1]))
        print("     （预期正确答案 0x03 / 比例 384）")


if __name__ == "__main__":
    main()
