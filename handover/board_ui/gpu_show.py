#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_show.py —— 让 FPGA GPU 独占屏幕画一张图 (停掉桌面后跑)
  这是最直接的证据: 屏幕上出现的东西完全是 PL 画出来的
"""
import sys, os, time, struct, mmap, fcntl, ctypes

sys.path.insert(0, "/home/zynq/ui")
from gpu import GPU

FB = "/dev/fb0"
W, H, STRIDE = 1024, 600, 3072


def fb_phys():
    class FBFix(ctypes.Structure):
        _fields_ = [("id", ctypes.c_char * 16), ("smem_start", ctypes.c_ulong),
                    ("smem_len", ctypes.c_uint32), ("type", ctypes.c_uint32),
                    ("type_aux", ctypes.c_uint32), ("visual", ctypes.c_uint32),
                    ("xpanstep", ctypes.c_uint16), ("ypanstep", ctypes.c_uint16),
                    ("ywrapstep", ctypes.c_uint16), ("__pad", ctypes.c_uint16),
                    ("line_length", ctypes.c_uint32)]
    fd = os.open(FB, os.O_RDWR)
    fix = FBFix()
    fcntl.ioctl(fd, 0x4602, fix)
    os.close(fd)
    if fix.smem_start:
        return fix.smem_start
    try:
        return int(open("/home/zynq/.fb_phys").read().strip(), 0)
    except Exception:
        return 0


def main():
    phys = fb_phys()
    print("显存物理地址 = 0x%08X" % phys)
    if not phys:
        print("拿不到物理地址"); return

    g = GPU(0x43CB0000, verbose=False)
    if not g.probe():
        print("GPU 不存在"); return
    print("GPU @0x43CB0000 存在 ✅")

    def op(opcode, x0, y0, x1, y1, color, name):
        """发一个操作, 发完等一会儿让 GPU 干完(不做 done 轮询, 因为那标志是单拍脉冲)"""
        g.clear_error()
        g.wr(0x08, phys); g.wr(0x0C, STRIDE)
        g.wr(0x10, ((x0 & 0xFFFF) << 16) | (y0 & 0xFFFF))
        g.wr(0x14, ((x1 & 0xFFFF) << 16) | (y1 & 0xFFFF))
        g.wr(0x18, color & 0xFFFFFF)
        g.wr(0x04, opcode)
        g.wr(0x00, 1)
        t0 = time.time()
        while time.time() - t0 < 2.0:
            n = g.rd(0x1C)
            exp = (x1 - x0 + 1) * (y1 - y0 + 1) if opcode == 0 else max(abs(x1-x0), abs(y1-y0)) + 1
            if n >= exp:
                break
            time.sleep(0.002)
        n = g.rd(0x1C)
        print("  %-28s -> %7d 像素  用时 %.1f ms" % (name, n, (time.time()-t0)*1000))

    t_all = time.time()
    # 1. 整屏刷成深蓝
    op(0, 0, 0, W - 1, H - 1, 0x101A30, "整屏填充 (深蓝)")
    # 2. 三个大色块
    op(0,  60,  90,  340, 330, 0xE03030, "红块 281x241")
    op(0, 372,  90,  652, 330, 0x30C060, "绿块 281x241")
    op(0, 684,  90,  964, 330, 0x3070E0, "蓝块 281x241")
    # 3. 黄色边框
    op(0,  20,  20, 1004,  30, 0xF0D030, "顶部黄条")
    op(0,  20, 570, 1004, 580, 0xF0D030, "底部黄条")
    # 4. 白色对角线
    op(1,  20, 350, 1004, 560, 0xFFFFFF, "白色对角线")
    op(1,  20, 560, 1004, 350, 0xFF40FF, "品红对角线")
    total = time.time() - t_all
    print("")
    print("共 8 个操作, 总耗时 %.1f ms" % (total * 1000))
    print("像素总数 ≈ %d 个 (整屏 614400 + 3 色块 + 边框 + 对角线)" %
          (W*H + 3*281*241 + 2*985*11 + 2*946))
    g.close()


main()
