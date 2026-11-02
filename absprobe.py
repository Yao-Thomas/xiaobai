#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读触摸设备的 ABS 量程（EVIOCGABS），并和屏幕尺寸对比"""
import fcntl
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ABS = {
    0x00: "ABS_X", 0x01: "ABS_Y", 0x02: "ABS_Z",
    0x35: "ABS_MT_POSITION_X", 0x36: "ABS_MT_POSITION_Y",
    0x37: "ABS_MT_TOOL_X", 0x38: "ABS_MT_TOOL_Y",
    0x30: "ABS_MT_TOUCH_MAJOR", 0x31: "ABS_MT_TOUCH_MINOR",
    0x39: "ABS_MT_TRACKING_ID", 0x3a: "ABS_MT_PRESSURE",
}


def eviocgabs(code):
    # _IOR('E', 0x40+code, struct input_absinfo)   input_absinfo = 6 * __s32
    return ((2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/dev/input/event1"
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    print("设备: %s" % path)
    try:
        # 先看 capabilities/abs 位图，知道支持哪些轴
        name = path.rsplit("/", 1)[-1]
        bitf = "/sys/class/input/%s/device/capabilities/abs" % name
        supported = None
        for cand in ("/sys/class/input/%s/capabilities/abs" % name, bitf):
            if os.path.exists(cand):
                supported = open(cand).read().strip()
                break
        print("capabilities/abs = %s" % supported)
        for code, nm in sorted(ABS.items()):
            try:
                buf = fcntl.ioctl(fd, eviocgabs(code), b"\0" * 24)
                val, mn, mx, fz, fl, res = struct.unpack("6i", buf)
                if mx == 0 and mn == 0:
                    continue
                print("  %-22s min=%-6d max=%-6d 当前=%-6d fuzz=%d flat=%d res=%d"
                      % (nm, mn, mx, val, fz, fl, res))
            except Exception:
                pass
    finally:
        os.close(fd)

    print()
    print("屏幕: 1024 x 600")
    print()
    print("★ 如果 max-min 不是 1024 / 600，代码里就必须做缩放，"
          "否则点哪儿都会偏。")


if __name__ == "__main__":
    main()
