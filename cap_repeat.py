#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_repeat.py —— 反复录，看采集信号是不是间歇性的

背景：cap_fix_test.py 里 D/E 两组测到 -46 dBFS（有信号），
      但后面单独试同样的寄存器值又是 -137（静音）。
      cap_keeper.py 持续纠正寄存器也救不回来。
      => 怀疑不是寄存器配置问题，而是【信号本身间歇】或者
         【板上压根没有麦克风，那两次是外来干扰/瞬态】。

做法：连录 N 次，每次 2 秒，把电平列出来。
      · 全部 -137           -> 确定没有信号源
      · 偶尔冒出 -4x        -> 干扰/瞬态，不是稳定信号
      · 全部 -4x            -> 真有信号，那前面的不一致要另找原因

用法:
    sudo python3 cap_repeat.py [次数]
"""
import array
import math
import os
import struct
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RATE = "44100"
CARD = "hw:0,1"


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
        pk = max(abs(x) for x in a)
        return out[0], out[1], pk, len(set(a))
    except Exception:
        return None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print("=" * 78)
    print(" 反复录音 %d 次（每次 2 秒），看信号是否稳定" % n)
    print("=" * 78)
    print("\n %-4s %-12s %-12s %-10s %-8s" % ("#", "ch0(dBFS)", "ch1(dBFS)", "峰值", "不同值"))
    print(" " + "-" * 54)

    hot = 0
    for k in range(n):
        path = "/tmp/rep.wav"
        try:
            os.remove(path)
        except OSError:
            pass
        p = subprocess.run(["arecord", "-q", "-D", CARD, "-f", "S24_LE",
                            "-r", RATE, "-c", "2", "-d", "2", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=20)
        lv = level(path) if os.path.exists(path) else None
        if not lv:
            print(" %-4d 录音失败" % (k + 1))
            continue
        flag = ""
        if lv[0] > -100:
            flag = "  ★"
            hot += 1
        print(" %-4d %-12.1f %-12.1f %-10d %-8d%s"
              % (k + 1, lv[0], lv[1], lv[2], lv[3], flag))
        time.sleep(0.3)

    print()
    print("=" * 78)
    if hot == 0:
        print(" 全部 -137 dBFS  ⇒ ★ 板上没有稳定的音频输入信号源")
        print("    可能原因（按可能性排序）：")
        print("      1. 板上没有板载麦克风，音频输入是个 3.5mm 插孔，没插东西")
        print("      2. 模拟前端（MIC 偏置/耦合电容）没焊或坏了")
        print("      3. PL 的 i2s_rx 没收到数据（但那样通常全 0，不是 -2）")
        print("    ★ 注意：数据是 ±2 而不是全 0，说明 I2S 时钟和 DMA 是通的，")
        print("      只是 ADC 输入端没有信号 —— 更像'没接输入'而不是'通路坏了'")
    elif hot == n:
        print(" 每次都 -4x dBFS  ⇒ 有稳定信号，前面的不一致要另找原因")
    else:
        print(" %d/%d 次有信号  ⇒ ★ 间歇性，说明是干扰或接触不良" % (hot, n))


if __name__ == "__main__":
    main()
