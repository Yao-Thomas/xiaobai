#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rec_buzz_test.py —— 用【蜂鸣器当声源】验证录音链路（不需要耳朵）

思路：
    蜂鸣器就在板子上，响起来是实打实的物理声音。
    如果在"静音"和"蜂鸣器响"两段录音里，RMS 明显不同，
    就说明 麦克风 → ES8388 ADC → I2S接收 → S2MM → DDR 整条链路是通的。

对每种 ADC 输入选择都试一遍，找出哪个输入能听到声音。
"""
import math
import sys
import threading
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A            # noqa: E402
import beep as B                # noqa: E402


def rms24(words, shift):
    """按给定摆放取 24bit 有符号样本，返回 (rms, peak)"""
    if not words:
        return 0.0, 0
    s = 0
    peak = 0
    n = 0
    for w in words:
        v = (w >> shift) & 0xFFFFFF if shift else w & 0xFFFFFF
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
        time.sleep(0.05)
    raw = a.read_ring()
    a.stop()
    return [A.struct.unpack_from("<I", raw, i)[0]
            for i in range(0, len(raw) - 3, 4)]


def main():
    inps = sys.argv[1].split(",") if len(sys.argv) > 1 else [
        "lin1", "mic1", "mic2", "diff", "line"]
    have_beeper = B.open_beeper() is not None
    if not have_beeper:
        print("!! 没有蜂鸣器，无法做声源验证")
        return

    print("=" * 74)
    print(" 录音链路验证：静音 vs 蜂鸣器（蜂鸣器在板子上，是真实物理声音）")
    print("=" * 74)

    for inp in inps:
        print("\n########## ADC 输入 = %s ##########" % inp)
        a = A.AudioIn(verbose=False)
        try:
            a.codec_adc_up(inp)
            a.i2s_config()
            a.fmt_config()

            # 1) 静音段
            quiet = capture(a, 1.2)
            # 2) 蜂鸣器响的一段（后台线程嘀）
            def buzz():
                B.beep(1, 1200)          # 连续响 1.2 秒
            th = threading.Thread(target=buzz, daemon=True)
            th.start()
            time.sleep(0.05)
            loud = capture(a, 1.2)
            th.join(timeout=2)

            for tag, words in (("静音", quiet), ("蜂鸣器", loud)):
                for name, shift in (("低24位(rj)", 0), ("高24位(lj)", 8)):
                    r, pk = rms24(words, shift)
                    print("   %-6s %-12s  n=%-6d RMS=%-10.1f 峰值=%d"
                          % (tag, name, len(words), r, pk))
        except Exception as e:
            print("   !! %s: %s" % (type(e).__name__, e))
        finally:
            a.close()
        time.sleep(0.3)

    print("\n" + "=" * 74)
    print(" 判读：如果某个输入下 '蜂鸣器' 的 RMS/峰值 明显大于 '静音'，")
    print("       那个输入就是能听到声音的 —— 录音链路通。")
    print("=" * 74)


if __name__ == "__main__":
    main()
