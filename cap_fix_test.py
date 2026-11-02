#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_fix_test.py —— 采集通路修复试验

★ 2026-10-01 诊断结论
----------------------
寄存器 dump（用 I2C_SLAVE_FORCE 读出来的）：
    0x0A = 0x50   低2位=00  -> 输入选的是 MIC(LIN1/RIN1)  ✓ 本来是对的
    0x03 = 0xF9   bit3=1    -> ★ 麦克风偏置【关】
    0x19 = 0x22   左 PGA 低
    0x1A = 0x00   ★ 右 PGA = 0（最小增益）
    0x0D = 0x03

对照上一轮能录音的老代码（cap_adc_fix.py 里记录的）：
    0x03 = 0x51   -> bit3=0，偏置【开】
    0x0A = 0x00
    0x0D = 0x02

⇒ 最可疑的是 0x03 的 bit3（PdnMICB）：驱动把它设成 1（关偏置），
  如果板载是驻极体麦克风，没偏置就完全没有输出 -> 采到 -137 dBFS 静音。

本脚本逐项试，每试一项录 2 秒看电平，最后可选恢复原值。

用法:
    sudo python3 cap_fix_test.py            # 试验（不保留）
    sudo python3 cap_fix_test.py --keep     # 试验并把好用的值留下
    sudo python3 cap_fix_test.py --restore  # 恢复出厂（驱动原值）
"""
import array
import math
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, "/home/zynq")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from es8388_rw import Codec, NAMES

RATE = "44100"
CARD = "hw:0,1"

# 驱动原始值（用于恢复）
ORIG = {0x03: 0xF9, 0x0A: 0x50, 0x0D: 0x03, 0x19: 0x22, 0x1A: 0x00, 0x17: 0x00}


def rec(path, secs=2):
    try:
        os.remove(path)
    except OSError:
        pass
    p = subprocess.run(["arecord", "-q", "-D", CARD, "-f", "S24_LE", "-r", RATE,
                        "-c", "2", "-d", str(secs), path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=secs + 15)
    if p.returncode != 0 or not os.path.exists(path):
        return None
    return path


def level(path):
    """返回 (ch0_dBFS, ch1_dBFS, 峰值)"""
    try:
        data = open(path, "rb").read()
        i = data.find(b"data")
        if i < 0:
            return None
        hdr = i + 8
        afmt, nch, rate, brate, balign, bits = struct.unpack_from("<HHIIHH", data, 20)
        n = (len(data) - hdr) // balign
        a = array.array("i")
        a.frombytes(data[hdr:hdr + n * nch * 4])
        for k in range(len(a)):
            if a[k] >= 0x800000:
                a[k] -= 0x1000000
        out = []
        for c in range(nch):
            xs = a[c::nch]
            rms = math.sqrt(sum(float(x) * x for x in xs) / len(xs))
            out.append(20 * math.log10(rms / 8388608.0) if rms > 0 else -999.0)
        pk = max(abs(x) for x in a)
        return out[0], out[1], pk
    except Exception as e:
        return None


def trial(c, label, writes):
    """改几个寄存器 -> 录 2 秒 -> 报电平"""
    for r, v in writes.items():
        c.wr(r, v)
    time.sleep(0.25)
    # 读回确认
    rb = "  ".join("0x%02X=0x%02X%s" % (r, c.rd(r),
                                        "" if c.rd(r) == v else "★")
                   for r, v in writes.items())
    p = rec("/tmp/fixtest.wav", 2)
    if not p:
        print("   %-34s 录音失败" % label)
        return None
    lv = level(p)
    if not lv:
        print("   %-34s 解析失败" % label)
        return None
    print("   %-34s ch0=%7.1f dBFS  ch1=%7.1f dBFS  峰=%d" % (label, lv[0], lv[1], lv[2]))
    print("        %s" % rb)
    return lv


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root")

    c = Codec()
    try:
        print("=" * 78)
        print(" 采集通路修复试验")
        print("=" * 78)

        print("\n>>> 0. 当前值")
        for r in sorted(ORIG):
            print("   0x%02X %-22s = 0x%02X" % (r, NAMES.get(r, ""), c.rd(r)))

        print("\n>>> 1. 基准（不改）")
        base = trial(c, "A 原样", {})

        print("\n>>> 2. 打开麦克风偏置（0x03 bit3 清零）")
        trial(c, "B 偏置开 0x03=0xF1", {0x03: 0xF1})

        print("\n>>> 3. 偏置开 + 左右 PGA 拉满")
        trial(c, "C +PGA=0x38/0x38", {0x03: 0xF1, 0x19: 0x38, 0x1A: 0x38})

        print("\n>>> 4. 再叠加上一轮老代码的值（0x0A=0x00, 0x0D=0x02）")
        trial(c, "D 老代码组合", {0x03: 0x51, 0x0A: 0x00, 0x0D: 0x02,
                                  0x19: 0x38, 0x1A: 0x38})

        print("\n>>> 5. 只改输入选择（保留偏置关）")
        trial(c, "E 只换输入 0x0A=0x00", {0x03: 0xF9, 0x0A: 0x00, 0x0D: 0x03,
                                          0x19: 0x22, 0x1A: 0x00})

        print("\n>>> 6. ADC 数字/模拟增益最大")
        trial(c, "F 0x17=0x00 0x18=0xFF", {0x03: 0xF1, 0x19: 0x38, 0x1A: 0x38,
                                           0x17: 0x00, 0x18: 0xFF})

        keep = "--keep" in sys.argv
        restore = "--restore" in sys.argv or not keep
        if restore:
            print("\n>>> 7. 恢复驱动原值")
            for r, v in ORIG.items():
                c.wr(r, v)
            print("   已恢复: " + "  ".join("0x%02X=0x%02X" % (r, c.rd(r))
                                            for r in sorted(ORIG)))
        else:
            print("\n>>> 7. --keep：保留当前（D 组）的值")
            for r, v in {0x03: 0x51, 0x0A: 0x00, 0x0D: 0x02,
                         0x19: 0x38, 0x1A: 0x38}.items():
                c.wr(r, v)
            print("   已写入: " + "  ".join("0x%02X=0x%02X" % (r, c.rd(r))
                                            for r in (0x03, 0x0A, 0x0D, 0x19, 0x1A)))

        print()
        print("★ 判读：")
        print("   某一组电平明显高于基准(-137) -> 就是那个寄存器，用 --keep 固化")
        print("   所有组都还是 -137          -> 不是 codec 配置问题")
        print("                                 可能是：板上没有麦克风(只有 LINE IN)")
        print("                                 或模拟前端没焊/PL 的 i2s_rx 没数据")
    finally:
        c.close()


if __name__ == "__main__":
    main()
