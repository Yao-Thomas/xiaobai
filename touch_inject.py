#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""touch_inject.py —— 往 GT911 注入一次触摸（板子上自己测 UI 用）

════════════════════════════════════════════════════════════════════
为什么需要
════════════════════════════════════════════════════════════════════
板子的 UI 是触摸驱动的，我（AI）看不到屏幕也不能用手指点。
如果不注入触摸，我就只能靠"离屏渲染"猜界面长什么样 ——
而离屏渲染跟真实运行【可能不一样】（比如 desktop 的状态、
App 的双缓冲页码、字体缓存等）。

FBUI 的触摸走 evdev（/dev/input/event1 = GT911）。
以前一直用 python-uinput，但板子上不一定装了。
所以这个脚本【不依赖第三方库】，直接写 /dev/uinput：
    UI_SET_EVBIT / UI_SET_KEYBIT / UI_SET_ABSBIT
    ABS_MT_POSITION_X / Y + ABS_MT_SLOT + ABS_MT_TRACKING_ID
    BTN_TOUCH
然后写 input_event 结构体（struct input_event: timeval + type + code + value）

用法（板子上，root）:
    sudo python3 touch_inject.py 175 150          # 点 (175,150)
    sudo python3 touch_inject.py 175 150 --hold 0.3
"""
import argparse
import ctypes
import fcntl
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UINPUT = "/dev/uinput"

# uinput ioctl
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

ABS_MT_SLOT = 0x2f
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39

BTN_TOUCH = 0x14a

SYN_REPORT = 0

# input_event: struct timeval(2*long) + __u16 type + __u16 code + __s32 value
# armv7: long = 4 字节  -> 16 字节
EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)


def emit(fd, etype, code, value):
    t = time.time()
    data = struct.pack(EV_FMT, int(t), int((t % 1) * 1e6), etype, code, value)
    os.write(fd, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("--hold", type=float, default=0.12,
                    help="按住多久（秒）")
    a = ap.parse_args()

    if not os.path.exists(UINPUT):
        print("★ 板子上没有 %s（内核没编 uinput），换个办法" % UINPUT)
        return 1

    fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)

    # 告诉内核我们要发什么
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
    fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH)
    for c in (ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y,
              ABS_MT_TRACKING_ID):
        fcntl.ioctl(fd, UI_SET_ABSBIT, c)

    # 设备描述
    class UInputUserDev(ctypes.Structure):
        _fields_ = [("name", ctypes.c_char * 80),
                    ("id_bustype", ctypes.c_uint16),
                    ("id_vendor", ctypes.c_uint16),
                    ("id_product", ctypes.c_uint16),
                    ("id_version", ctypes.c_uint16),
                    ("ff_effects_max", ctypes.c_uint32),
                    ("absmax", ctypes.c_int32 * 64),
                    ("absmin", ctypes.c_int32 * 64),
                    ("absfuzz", ctypes.c_int32 * 64),
                    ("absflat", ctypes.c_int32 * 64)]

    dev = UInputUserDev()
    dev.name = b"dsh-touch-inject"
    dev.id_bustype = 0x03          # BUS_USB
    dev.id_vendor = 0x1234
    dev.id_product = 0x5678
    dev.absmax[ABS_MT_POSITION_X] = 1024
    dev.absmax[ABS_MT_POSITION_Y] = 600
    dev.absmax[ABS_MT_SLOT] = 9
    dev.absmax[ABS_MT_TRACKING_ID] = 65535

    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.4)                 # 等 udev/上层认到设备

    try:
        # ── 按下 ──
        emit(fd, EV_ABS, ABS_MT_SLOT, 0)
        emit(fd, EV_ABS, ABS_MT_TRACKING_ID, 1)
        emit(fd, EV_ABS, ABS_MT_POSITION_X, a.x)
        emit(fd, EV_ABS, ABS_MT_POSITION_Y, a.y)
        emit(fd, EV_KEY, BTN_TOUCH, 1)
        emit(fd, EV_SYN, SYN_REPORT, 0)
        time.sleep(a.hold)
        # ── 抬起 ──
        emit(fd, EV_ABS, ABS_MT_TRACKING_ID, -1)
        emit(fd, EV_KEY, BTN_TOUCH, 0)
        emit(fd, EV_SYN, SYN_REPORT, 0)
        time.sleep(0.15)
        print("  ✓ 已注入触摸 (%d, %d)" % (a.x, a.y))
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
