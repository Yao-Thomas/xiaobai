#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_keeper.py —— 录音期间持续纠正 codec 寄存器（对抗驱动覆盖）

★ 为什么需要
------------
前面 cap_fix_test.py 和 cap_bit_scan.py 结果矛盾：
    同样把 0x0A 写成 0x00，有时 ch0 = -46 dBFS（有信号），
    有时又是 -137 dBFS（静音）。

原因：es8388 内核驱动在 **PCM 流启动时**（arecord open 设备那一刻）
      会重新下发一遍寄存器，把我们的修改冲掉。
      所以"先写寄存器再录音"是赛跑，赢不赢看运气。

做法：先启动 arecord，然后一边录一边以 ~20Hz 频率重写目标寄存器，
      同时记录每次读回的值，看驱动到底改了什么、改成什么。

用法:
    sudo python3 cap_keeper.py                    # 试 0x0A=0x00
    sudo python3 cap_keeper.py --regs 0x0A=0x00,0x03=0xF1
"""
import array
import math
import os
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/home/zynq")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from es8388_rw import Codec

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
        return out[0], out[1], pk
    except Exception:
        return None


def run_trial(secs, targets, label, watch_regs):
    """启动录音 -> 持续写 targets -> 记录 watch_regs 的变化"""
    path = "/tmp/keeper.wav"
    try:
        os.remove(path)
    except OSError:
        pass

    print("\n--- %s ---" % label)
    print("   目标: " + "  ".join("0x%02X=0x%02X" % (r, v) for r, v in targets.items()))

    p = subprocess.Popen(["arecord", "-q", "-D", CARD, "-f", "S24_LE",
                          "-r", RATE, "-c", "2", "-d", str(secs), path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.35)          # 等流起来（驱动就是在这时候重写寄存器的）

    c = Codec()
    t0 = time.time()
    writes = 0
    seen = {}                 # reg -> 见过的值集合
    changes = []              # (t, reg, old, new)
    while time.time() - t0 < secs - 0.3:
        for r in watch_regs:
            v = c.rd(r)
            seen.setdefault(r, set()).add(v)
        for r, v in targets.items():
            cur = c.rd(r)
            if cur != v:
                c.wr(r, v)
                changes.append((time.time() - t0, r, cur, v))
                writes += 1
        time.sleep(0.05)
    c.close()
    p.wait()

    print("   纠正写入次数: %d" % writes)
    if changes:
        print("   前 8 次纠正:")
        for t, r, old, new in changes[:8]:
            print("      t=%.2fs  0x%02X: 0x%02X -> 0x%02X" % (t, r, old, new))
    print("   各寄存器在录音期间出现过的值:")
    for r in watch_regs:
        vals = sorted(seen.get(r, []))
        print("      0x%02X: %s" % (r, " ".join("0x%02X" % v for v in vals)))

    lv = level(path) if os.path.exists(path) else None
    if lv:
        print("   ★ 电平: ch0=%.1f dBFS  ch1=%.1f dBFS  峰值=%d"
              % (lv[0], lv[1], lv[2]))
    else:
        print("   ★ 录音/解析失败")
    return lv


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root")

    targets = {0x0A: 0x00}
    if "--regs" in sys.argv:
        spec = sys.argv[sys.argv.index("--regs") + 1]
        targets = {}
        for kv in spec.split(","):
            k, v = kv.split("=")
            targets[int(k, 0)] = int(v, 0)

    watch = [0x0A, 0x03, 0x0D, 0x17, 0x19, 0x1A, 0x02]

    print("=" * 78)
    print(" 录音期间持续纠正寄存器（对抗驱动覆盖）")
    print("=" * 78)

    # 对照组：不纠正
    print("\n>>> 对照组：录音期间**不**写寄存器")
    p = subprocess.Popen(["arecord", "-q", "-D", CARD, "-f", "S24_LE",
                          "-r", RATE, "-c", "2", "-d", "2", "/tmp/ctrl.wav"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.35)
    c = Codec()
    vals = {}
    for _ in range(30):
        for r in watch:
            vals.setdefault(r, set()).add(c.rd(r))
        time.sleep(0.05)
    c.close()
    p.wait()
    print("   录音期间各寄存器的值:")
    for r in watch:
        print("      0x%02X: %s" % (r, " ".join("0x%02X" % v
                                                for v in sorted(vals.get(r, [])))))
    lv = level("/tmp/ctrl.wav")
    if lv:
        print("   ★ 电平: ch0=%.1f dBFS  ch1=%.1f dBFS" % (lv[0], lv[1]))

    # 实验组
    run_trial(3, targets, "实验组：持续写 " +
              " ".join("0x%02X=0x%02X" % (r, v) for r, v in targets.items()),
              watch)

    print()
    print("★ 判读：")
    print("   · 对照组里 0x0A 若在录音中途从 0x00 变成 0x50（或反之）")
    print("     -> 坐实了'驱动在流启动时重写'")
    print("   · 实验组电平明显高于对照组 -> 持续纠正有效，可以固化进服务")
    print("   · 两组都 -137 -> 板上确实没麦克风信号源，不是配置问题")


if __name__ == "__main__":
    main()
