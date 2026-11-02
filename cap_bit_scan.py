#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_bit_scan.py —— 逐位定位寄存器 0x0A 里到底是哪位让左声道活过来的

背景：cap_fix_test.py 的结果
    A/B/C/F（0x0A = 0x50）    -> ch0 = -137.2 dBFS   静音
    D/E    （0x0A = 0x00）    -> ch0 =  -46.x dBFS   有信号 ★

0x50 和 0x00 的低 2 位都是 00（都选 LIN1/RIN1），差别在高位。
所以逐个 bit 试，找出关键位，而不是盲写 0x00（0x00 可能顺带关掉了
别的东西）。

同时观察右声道：如果怎么试都是 -137，说明板上是单声道麦克风
（只接左声道），那属于正常设计，不是 bug。
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
BASE_0A = 0x50          # 驱动的默认值


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
        return out[0], out[1]
    except Exception:
        return None


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root")
    c = Codec()
    try:
        print("=" * 78)
        print(" 寄存器 0x0A 逐位扫描（找让左声道复活的那一位）")
        print("=" * 78)
        print("\n 基线：驱动原值 0x0A = 0x%02X" % BASE_0A)

        results = []
        # 先测基线，再逐个清掉一位
        tests = [("基线 0x50", 0x50), ("基线 0x00", 0x00)]
        for b in range(7):
            v = BASE_0A & ~(1 << b)
            tests.append(("清 bit%d -> 0x%02X" % (b, v), v))
        # 再去掉某一位单独置
        for b in range(7):
            v = 0x00 | (1 << b)
            tests.append(("只置 bit%d -> 0x%02X" % (b, v), v))

        print("\n %-24s %-14s %-14s" % ("设置", "ch0(dBFS)", "ch1(dBFS)"))
        print(" " + "-" * 56)
        for label, val in tests:
            c.wr(0x0A, val)
            time.sleep(0.2)
            got = c.rd(0x0A)
            p = rec("/tmp/bitscan.wav", 2)
            lv = level(p) if p else None
            if lv:
                flag = ""
                if lv[0] > -80:
                    flag = "  ★ 左声道有信号"
                print(" %-24s %-14.1f %-14.1f%s" % (label, lv[0], lv[1], flag))
                results.append((label, val, got, lv))
            else:
                print(" %-24s 录音/解析失败" % label)

        # 恢复
        c.wr(0x0A, BASE_0A)
        print("\n 已恢复 0x0A = 0x%02X" % c.rd(0x0A))

        print()
        print("★ 判读")
        good = [r for r in results if r[3][0] > -80]
        if not good:
            print("  没有一组能让左声道出声 —— 和数据通路有关，不是 0x0A")
        else:
            print("  以下设置让左声道有信号：")
            for lb, v, got, lv in good:
                print("    %-24s (写 0x%02X, 读回 0x%02X)  ch0=%.1f dBFS"
                      % (lb, v, got, lv[0]))
            vals = set(v for _, v, _, _ in good)
            if len(vals) == 1:
                print("  ⇒ 唯一有效值 0x%02X" % list(vals)[0])
            else:
                # 找共同点
                common_clear = 0xFF
                for v in vals:
                    common_clear &= v
                print("  ⇒ 多个值有效，它们的公共位 = 0x%02X（这些位可以保持）" % common_clear)
                print("     无效值里置 1 的位就是【关键位】")

        print()
        print("★ 右声道：如果从头到尾都是 -137，说明板上是单声道麦克风"
              "（只接左声道），属正常设计")
    finally:
        c.close()


if __name__ == "__main__":
    main()
