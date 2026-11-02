#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serial_probe.py —— 探测板子串口上有没有任何输出

板子在 RTC 唤醒测试里 poweroff 之后就没回来，ping 不通、串口也没回显。
本脚本只做一件事：打开串口、读 N 秒原始数据、原样打印出来。

判读：
  有启动日志（U-Boot/kernel）  -> 板子其实在重启循环
  完全空白                     -> 板子处于停机/断电，需要物理上电
  只有零星乱码                 -> 波特率不对或板子半死

用法:
    python serial_probe.py [秒数] [COM口]
"""
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("需要 pyserial: pip install pyserial")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

secs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
port = sys.argv[2] if len(sys.argv) > 2 else "COM6"

print("=" * 70)
print(" 串口探测: %s @115200, 读 %d 秒" % (port, secs))
print("=" * 70)

try:
    ser = serial.Serial(port, 115200, timeout=0.3)
except Exception as e:
    sys.exit("★ 打不开 %s : %s\n  （XCOM 之类的工具是不是占着？）" % (port, e))

print(" 串口已打开。先敲几次回车唤醒 console...")
for _ in range(3):
    ser.write(b"\r\n")
    time.sleep(0.25)

# 顺便发一个 Ctrl-C，万一正好卡在某个前台进程里
ser.write(b"\x03")
time.sleep(0.3)

print(" 开始读 %d 秒（原样打印）...\n" % secs)
t0 = time.time()
total = 0
while time.time() - t0 < secs:
    try:
        data = ser.read(4096)
    except Exception as e:
        print("  读取出错: %s" % e)
        break
    if data:
        total += len(data)
        try:
            sys.stdout.write(data.decode("utf-8", errors="replace"))
        except Exception:
            sys.stdout.write(repr(data))
        sys.stdout.flush()
    time.sleep(0.05)

print("\n" + "=" * 70)
print(" 共收到 %d 字节" % total)
if total == 0:
    print(" ★ 完全没有输出")
    print("   ⇒ 板子处于停机/断电状态，需要物理断电再上电")
    print("   （RTC 闹钟没能从 poweroff 唤醒它）")
elif total < 40:
    print(" ★ 只有极少数据 —— 可能波特率不对，或板子半死")
else:
    print(" ★ 有数据 —— 板子可能在重启，上面就是启动日志")
print("=" * 70)
ser.close()
