#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_adc_fix.py —— 验证"把 ADC 配成麦克风输入"能不能救活录音

实测对比（采集进行中 dump ES8388）：

    reg    驱动设的   我老代码能录音的值   含义
    0x03   0x09       0x51                 ADC 电源（bit3=PdnMICB，1=偏置关）
    0x0A   0x50       0x00                 ADC 输入选择（0x00=LIN1/RIN1 麦克风）
    0x0D   0x03       0x02                 ADC 控制5

0x0A=0x50 很可能是选了 **LINE 输入**（板子上没接东西）-> 采到全零。

做法：arecord 跑起来 -> 改成可用值 -> 看数据变不变 -> 再改回去对比。
"""
import math
import struct
import subprocess
import sys
import time
import wave

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from audio_pl import I2C                                       # noqa: E402

# 我老代码里"已知能录音"的 ADC 配置
GOOD = [(0x03, 0x51), (0x0A, 0x00), (0x0D, 0x02)]
# 驱动当前的（用来对照 / 恢复）
DRV = [(0x03, 0x09), (0x0A, 0x50), (0x0D, 0x03)]


def stats(path):
    try:
        w = wave.open(path, "rb")
        n, sw = w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
        w.close()
        if sw == 4:
            v = list(struct.unpack("<%di" % (len(raw) // 4), raw))
            FULL = 2147483647.0
        else:
            v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
            FULL = 32767.0
        if not v:
            return "空"
        rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
        pk = max(abs(x) for x in v)
        return ("不同取值=%-6d RMS=%-10.0f (%6.1f dBFS) 峰值=%.1f%%"
                % (len(set(v)), rms,
                   20 * math.log10(max(1e-9, rms / FULL)), pk / FULL * 100))
    except Exception as e:
        return "读失败: %s" % e


def rec(secs, path):
    subprocess.run(["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE",
                    "-r", "44100", "-c", "2", "-d", str(secs), path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    i2c = I2C()
    print("=" * 82)
    print("验证：把 ADC 改成麦克风输入")
    print("=" * 82)
    print()
    print("当前寄存器:")
    for r, _ in DRV:
        print("  0x%02X = 0x%02X" % (r, i2c.rd(r)))
    print()

    # ---- A: 原样录（对照）----
    print("--- A) 驱动原样，录 2 秒 ---")
    rec(2, "/tmp/adc_A.wav")
    print("   ", stats("/tmp/adc_A.wav"))
    print()

    # ---- B: 改成可用值 ----
    print("--- B) 采集期间改成 0x03=0x51 0x0A=0x00 0x0D=0x02（麦克风输入）---")
    p = subprocess.Popen(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-r", "44100",
         "-c", "2", "-d", "4", "/tmp/adc_B.wav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    for r, v in GOOD:
        i2c.wr(r, v)
    time.sleep(0.15)
    print("   写入后: " + "  ".join("0x%02X=0x%02X" % (r, i2c.rd(r)) for r, _ in GOOD))
    # 持续纠正（驱动可能改回去）
    for k in range(7):
        for r, v in GOOD:
            if i2c.rd(r) != v:
                i2c.wr(r, v)
                print("   第 %d 次纠正 0x%02X -> 0x%02X" % (k + 1, r, v))
        time.sleep(0.45)
    p.wait()
    print("   arecord 退出码:", p.returncode)
    print("   ", stats("/tmp/adc_B.wav"))
    print()

    # ---- C: 长时间再测一次，确认稳定 ----
    print("--- C) 再来 3 秒，持续纠正 ---")
    p = subprocess.Popen(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-r", "44100",
         "-c", "2", "-d", "3", "/tmp/adc_C.wav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    for k in range(12):
        for r, v in GOOD:
            i2c.wr(r, v)
        time.sleep(0.2)
    p.wait()
    print("   ", stats("/tmp/adc_C.wav"))

    i2c.close()
    print()
    print("★ 判读：")
    print("  A 全零 + B/C 有明显 RMS -> **ADC 输入选错就是根因**（0x0A 要从 0x50 改成 0x00）")
    print("  三段都全零 -> 还有别的问题（模拟前端 / 麦克风本身）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
