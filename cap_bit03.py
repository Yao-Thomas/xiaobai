#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_bit03.py —— 精确定位寄存器 0x03 的哪一位让 ADC 活过来

★ 推理过程
----------
1. ALSA 采集一直 -137 dBFS（数字静音）
2. 跑完 PL 工具 rec_big.py 之后，ALSA 突然能采到 -68 dBFS
3. 对比两边留下的 0x03：
       PL 工具（能用）  = 0x59 = 0101 1001
       ALSA 驱动（不能用）= 0xF9 = 1111 1001
   只差 bit7 和 bit6。
4. 我之前试过 0xF1 = 1111 0001（bit3=0，以为那是麦克风偏置），
   没用 —— 因为 bit7 还是 1。

ES8388 寄存器 0x03（ADC Power Management）常见位定义：
   bit7  PdnADCB   1 = 两个 ADC 都断电
   bit6  PdnMICB   1 = 麦克风偏置关
   bit5  PdnADCL   1 = 左 ADC 断电
   bit4  PdnADCR   1 = 右 ADC 断电

所以最可能是 bit7。本脚本逐位验证，并顺带确认"驱动会不会在流启动时改回去"。

用法:
    sudo python3 cap_bit03.py
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

from es8388_rw import Codec

RATE = "44100"
CARD = "hw:0,1"


def rec(path, secs=2):
    try:
        os.remove(path)
    except OSError:
        pass
    p = subprocess.run(["arecord", "-q", "-D", CARD, "-f", "S24_LE", "-r", RATE,
                        "-c", "2", "-d", str(secs), path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=secs + 15)
    return path if (p.returncode == 0 and os.path.exists(path)) else None


def level(path):
    try:
        data = open(path, "rb").read()
        i = data.find(b"data")
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
        return out[0], out[1], max(abs(x) for x in a)
    except Exception:
        return None


def bits(v):
    return "".join("1" if (v >> b) & 1 else "0" for b in range(7, -1, -1))


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root")
    c = Codec()
    try:
        print("=" * 80)
        print(" 寄存器 0x03 逐位验证（找让 ADC 活过来的那一位）")
        print("=" * 80)

        DRV = 0xF9
        PL = 0x59

        print("\n 参考值：")
        print("   ALSA 驱动(静音)  0x%02X = %s" % (DRV, bits(DRV)))
        print("   PL 工具(能用)    0x%02X = %s" % (PL, bits(PL)))
        diff = DRV ^ PL
        print("   差异位: " + " ".join("bit%d" % b for b in range(8) if (diff >> b) & 1))

        tests = []
        for b in range(8):
            tests.append(("清 bit%d (0x%02X)" % (b, DRV & ~(1 << b)), DRV & ~(1 << b)))
        tests.append(("PL 值 0x59", PL))
        tests.append(("驱动原值 0xF9", DRV))

        print("\n %-22s %-12s %-12s %-10s" % ("0x03 的值", "ch0(dBFS)", "ch1(dBFS)", "峰值"))
        print(" " + "-" * 60)

        best = []
        for label, val in tests:
            c.wr(0x03, val)
            time.sleep(0.3)
            got = c.rd(0x03)
            p = rec("/tmp/b03.wav", 2)
            lv = level(p) if p else None
            if not lv:
                print(" %-22s 录音失败" % label)
                continue
            flag = ""
            if lv[0] > -100:
                flag = "  ★ 有信号！"
                best.append((label, val, lv[0]))
            print(" %-22s %-12.1f %-12.1f %-10d%s"
                  % (label, lv[0], lv[1], lv[2], flag))
            if got != val:
                print("       (读回 0x%02X —— 被驱动改了)" % got)

        # 恢复
        c.wr(0x03, DRV)
        print("\n 已恢复 0x03 = 0x%02X" % c.rd(0x03))

        print()
        print("=" * 80)
        if not best:
            print(" 没有一组能让采集出声 —— 需要重新考虑")
        else:
            print(" ★ 有效的设置：")
            for lb, v, l in best:
                print("     %-22s 0x%02X -> ch0 = %.1f dBFS" % (lb, v, l))
            vals = set(v for _, v, _ in best)
            if PL in vals or (DRV & ~0x80) in vals:
                print()
                print(" ⇒ 结论：★ 关键就是 0x03 的 bit7（PdnADCB，ADC 总断电位）")
                print("   驱动把它设成 1 了 -> ADC 不工作 -> 采到数字静音")
                print("   修法：录音前把它清成 0（0x%02X），或持续纠正" % (DRV & ~0x80))
    finally:
        c.close()


if __name__ == "__main__":
    main()
