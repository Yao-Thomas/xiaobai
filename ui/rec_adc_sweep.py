#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_adc_sweep.py —— 扫 ES8388 的 ADC 电源寄存器 0x03，找出能让 ADC 吐数据的值

位定义（es8328.h，都是「1 = 关」）:
    bit0 INT1_LOWPOWER      bit1 FLASH_ADC_LOWPOWER
    bit2 ADC_BIAS_GEN_OFF   bit3 MIC_BIAS_OFF
    bit4 ADCR_OFF           bit5 ADCL_OFF
    bit6 AINR_OFF           bit7 AINL_OFF

厂家初始化写的是 0x59 = 0101_1001 -> 右 ADC 和右输入都是关的，只开左路。
本脚本把候选值一个个试，看谁能让录到的数据"不是死的"。

判据（在样本数据上算）:
    uniq   = 一整个环形缓冲里出现过多少种不同的 24bit 值
    peak   = 绝对值最大
    如果一个音频输入都没接/没转换，数据会是极少数几个固定值（甚至只有 1~2 种）
"""
import sys
import threading
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402
import beep as B                # noqa: E402


def analyze(a, secs=0.8):
    """录一小段，返回 (uniq数, 峰值, 前几个样本)"""
    a.start()
    t_end = time.time() + secs
    while time.time() < t_end:
        a.poll_pos()
        time.sleep(0.03)
    raw = a.read_ring()
    a.stop()
    words = [A.struct.unpack_from("<I", raw, i)[0]
             for i in range(0, len(raw) - 3, 4)]
    # 两种解释都算一下
    res = {}
    for tag, sh in (("低24", 0), ("[27:4]", 4)):
        vals = []
        for w in words:
            v = (w >> sh) & 0xFFFFFF
            if v & 0x800000:
                v -= 1 << 24
            vals.append(v)
        res[tag] = (len(set(vals)), max(abs(v) for v in vals) if vals else 0,
                    vals[:4])
    return res


def main():
    adc_in = sys.argv[1] if len(sys.argv) > 1 else "lin1"
    cands = [int(x, 16) for x in (sys.argv[2].split(",") if len(sys.argv) > 2
                                  else ["59", "09", "01", "00", "19", "49",
                                        "08", "51", "41", "11"])]

    print("=" * 78)
    print(" 扫 ADC 电源寄存器 0x03   (ADC输入=%s)" % adc_in)
    print(" 候选值按位拆解： AINL AINR ADCL ADCR MICBIAS BIASGEN")
    print("=" * 78)

    def bits(v):
        return "  %d    %d    %d    %d     %d(=关)   %d(=关)" % (
            (v >> 7) & 1, (v >> 6) & 1, (v >> 5) & 1, (v >> 4) & 1,
            (v >> 3) & 1, (v >> 2) & 1)

    best = None
    for v in cands:
        a = A.AudioIn(verbose=False)
        try:
            a.codec_adc_up(adc_in)
            a.i2c.wr(0x03, v)              # ★ 覆盖 ADC 电源
            a.i2s_config()
            a.fmt_config()
            res = analyze(a, 0.8)
            lo = res["低24"]
            mid = res["[27:4]"]
            score = max(lo[0], mid[0])
            tag = ""
            if best is None or score > best[1]:
                best = (v, score)
                tag = "   <== 目前最好"
            print(" 0x%02X%s | 低24: uniq=%-6d peak=%-8d | [27:4]: uniq=%-6d peak=%-8d%s"
                  % (v, bits(v), lo[0], lo[1], mid[0], mid[1], tag))
        except Exception as e:
            print(" 0x%02X !! %s: %s" % (v, type(e).__name__, e))
        finally:
            a.close()
        time.sleep(0.15)

    print("=" * 78)
    if best:
        print(" >>> 数据最活的 0x03 = 0x%02X (uniq=%d)" % (best[0], best[1]))
        print("     如果所有候选的 uniq 都只有 1~2，说明 ADC 根本没在转换，")
        print("     或者 ASDOUT 没被驱动 -> 要往 codec 之外查（I2S 接收器/引脚）")


if __name__ == "__main__":
    main()
