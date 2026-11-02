# -*- coding: utf-8 -*-
"""try_serial.py —— 只试 USB 转串口那几个口 (COM5/6/7), 跳过蓝牙口

蓝牙串口(COM3/COM4)打开会阻塞, 所以不碰它们。
"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

CANDIDATES = ["COM5", "COM6", "COM7"]
BAUD = 115200

for port in CANDIDATES:
    try:
        s = serial.Serial(port, BAUD, timeout=0.5, write_timeout=0.5)
    except Exception as e:
        print("%-6s 打不开: %s: %s" % (port, type(e).__name__, e))
        continue
    try:
        s.reset_input_buffer()
        s.write(b"\r\n")
        time.sleep(0.5)
        data = s.read(300)
        if data:
            print("%-6s 有数据:" % port)
            for line in data.decode("utf-8", "replace").replace("\r", "").splitlines()[:15]:
                print("      " + line)
        else:
            print("%-6s 打开成功, 但没读到数据 (板子可能没在输出, 或者不是这个口)" % port)
    finally:
        try:
            s.close()
        except Exception:
            pass

print("完")
