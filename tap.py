#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tap.py —— 直接往触摸设备写 input_event，模拟点击

桌面用 Touch() 类读 /dev/input/event*，没有现成的注入通道
（我原来的 /tmp/ui_tap 被换掉了）。这里直接写事件结构：

    struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
    32 位 ARM Linux 上 timeval 是 8 字节 -> 结构共 16 字节

用法:  sudo python3 tap.py X Y [X2 Y2 ...]
"""
import struct
import sys
import time

DEV = "/dev/input/event1"          # Goodix Capacitive TouchScreen

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0
BTN_TOUCH = 0x14A
ABS_X = 0x00
ABS_Y = 0x01


def ev(t, c, v):
    return struct.pack("<llHHi", 0, 0, t, c, v)


def tap(f, x, y, hold=0.06):
    f.write(ev(EV_ABS, ABS_X, int(x)))
    f.write(ev(EV_ABS, ABS_Y, int(y)))
    f.write(ev(EV_KEY, BTN_TOUCH, 1))
    f.write(ev(EV_SYN, SYN_REPORT, 0))
    f.flush()
    time.sleep(hold)
    f.write(ev(EV_KEY, BTN_TOUCH, 0))
    f.write(ev(EV_SYN, SYN_REPORT, 0))
    f.flush()


def main():
    if len(sys.argv) < 3:
        print("用法: sudo python3 tap.py X Y [X2 Y2 ...]")
        return 1
    pts = sys.argv[1:]
    with open(DEV, "wb") as f:
        for i in range(0, len(pts) - 1, 2):
            x, y = int(pts[i]), int(pts[i + 1])
            print("  点击 (%d, %d)" % (x, y))
            tap(f, x, y)
            time.sleep(1.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
