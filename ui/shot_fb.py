#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_fb.py —— 正确读 Zynq 帧缓冲的截图工具（在【板子上】跑）

问题：/dev/fb0 的 virtual_size 是 1024x1200（双缓冲），屏幕只有 600 行。
      固定读前 600 行时，若桌面正渲染在另一半，就会截到**过期的旧画面**
      （表现为连续截图哈希完全相同，看着像"屏幕冻住"）。

做法：用 FBIOGET_VSCREENINFO 查真实 yoffset，只取当前可见的 600 行，
      输出 BGR24 原始数据（PIL 用 "raw","BGR" 直接读）。

用法（板上）: sudo python3 shot_fb.py /tmp/shot.raw
"""
import fcntl
import struct
import sys

FBIOGET_VSCREENINFO = 0x4600

# ★ 实测这块 fb 是 24bpp 打包 BGR：stride = 1024 * 3 = 3072
#   （不是 32bpp！按 4 字节/像素读会让画面横向压缩并重复 4 次）
BYTES_PER_PIXEL = 3


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shot.raw"
    with open("/dev/fb0", "rb") as f:
        buf = bytearray(256)
        fcntl.ioctl(f.fileno(), FBIOGET_VSCREENINFO, buf, True)
        (xres, yres, xres_v, yres_v,
         xoff, yoff) = struct.unpack("<6I", bytes(buf[:24]))
        bpp = struct.unpack("<I", bytes(buf[24:28]))[0]
        sys.stderr.write("  fb: 可见 %dx%d  虚拟 %dx%d  偏移(%d,%d)  bpp=%d\n"
                         % (xres, yres, xres_v, yres_v, xoff, yoff, bpp))

        stride = xres_v * BYTES_PER_PIXEL

        # 跳到当前可见区域的起点
        f.seek(yoff * stride + xoff * BYTES_PER_PIXEL)

        with open(out, "wb") as g:
            for _ in range(yres):
                line = f.read(stride)
                if len(line) < xres * BYTES_PER_PIXEL:
                    line = line + b"\x00" * (xres * BYTES_PER_PIXEL - len(line))
                g.write(line[:xres * BYTES_PER_PIXEL])

    sys.stderr.write("  已写 %s\n" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
