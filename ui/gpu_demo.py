#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_demo.py —— FPGA GPU 上板验证
  1) 从 /dev/fb0 的 ioctl 拿到【显存的物理地址】(FBIOGET_FSCREENINFO)
  2) 找到 PL 里的 GPU 寄存器
  3) 用 GPU 在显存上填充矩形 / 画直线  -> 屏幕直接变化
用法: sudo python3 gpu_demo.py
"""
import ctypes, fcntl, os, sys, time
sys.path.insert(0, "/home/zynq/ui")
from gpu import GPU, find_gpu

FBIOGET_FSCREENINFO = 0x4602
FBIOGET_VSCREENINFO = 0x4600


class FBFix(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),      # ★ 显存物理地址
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        ("__pad", ctypes.c_uint16),
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]


class FBVar(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_uint32), ("yres", ctypes.c_uint32),
        ("xres_virtual", ctypes.c_uint32), ("yres_virtual", ctypes.c_uint32),
        ("xoffset", ctypes.c_uint32), ("yoffset", ctypes.c_uint32),
        ("bits_per_pixel", ctypes.c_uint32), ("grayscale", ctypes.c_uint32),
        ("red", ctypes.c_uint32 * 4), ("green", ctypes.c_uint32 * 4),
        ("blue", ctypes.c_uint32 * 4), ("transp", ctypes.c_uint32 * 4),
        ("nonstd", ctypes.c_uint32), ("activate", ctypes.c_uint32),
        ("height", ctypes.c_uint32), ("width", ctypes.c_uint32),
        ("accel_flags", ctypes.c_uint32),
        ("pixclock", ctypes.c_uint32), ("left_margin", ctypes.c_uint32),
        ("right_margin", ctypes.c_uint32), ("upper_margin", ctypes.c_uint32),
        ("lower_margin", ctypes.c_uint32), ("hsync_len", ctypes.c_uint32),
        ("vsync_len", ctypes.c_uint32), ("sync", ctypes.c_uint32),
        ("vmode", ctypes.c_uint32), ("rotate", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32), ("reserved", ctypes.c_uint32 * 4),
    ]


def fb_phys():
    fd = os.open("/dev/fb0", os.O_RDWR)
    fix = FBFix()
    var = FBVar()
    fcntl.ioctl(fd, FBIOGET_FSCREENINFO, fix)
    fcntl.ioctl(fd, FBIOGET_VSCREENINFO, var)
    os.close(fd)
    return fix.smem_start, fix.smem_len, fix.line_length, var.xres, var.yres, var.bits_per_pixel


def main():
    print("=" * 56)
    print("  FPGA GPU 上板验证")
    print("=" * 56)
    print("")

    print("[1] 读取显存物理地址")
    phys, length, stride, w, h, bpp = fb_phys()
    print("    物理地址 = 0x%08X" % phys)
    print("    显存大小 = %d 字节" % length)
    print("    行跨距   = %d 字节" % stride)
    print("    分辨率   = %dx%d %dbpp" % (w, h, bpp))
    print("")
    if phys == 0:
        print("!! 物理地址为 0, 无法给 GPU 用")
        return

    print("[2] 寻找 PL 里的 GPU")
    g = find_gpu()
    if not g:
        print("")
        print(">>> GPU 不存在 —— bitstream 还没加载?")
        print("    (这是正常的, 等 Vivado 2020.2 集成好就有)")
        return
    print("")

    print("[3] 用 GPU 填充矩形 (直接改屏幕!)")
    for i, col in enumerate([0xE03030, 0x30C060, 0x3070E0]):
        g.fill(phys, stride, 80 + i * 300, 120, 240, 160, col)
        time.sleep(0.3)
    print("")

    print("[4] 用 GPU 画直线")
    g.line(phys, stride, 40, 400, w - 40, 400, 0xFFFFFF)
    g.line(phys, stride, 40, 400, 40, h - 60, 0xFFFF00)
    print("")

    print("[5] 性能对比 (填充整屏 1024x600)")
    t0 = time.time()
    n, ok = g.fill(phys, stride, 0, 0, w, h, 0x102040, )
    dt = time.time() - t0
    print("    硬件填充 %d 像素, 耗时 %.1f ms (%.1f MB/s)" %
          (n, dt * 1000, n * 3 / 1024.0 / 1024.0 / max(dt, 1e-6)))
    g.close()
    print("")
    print("=" * 56)


main()
