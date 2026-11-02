#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu_trace.py —— 找出 FPGA GPU 的写到底落到哪块内存
  做法: 用 GPU 写一个独特颜色, 然后在 /dev/mem 里搜它
"""
import sys, os, time, mmap, ctypes, fcntl
sys.path.insert(0, "/home/zynq/ui")
from gpu import GPU

FB_PHYS = 0x3F100000
STRIDE = 3072
PATTERN = 0x123456          # 独特颜色 R=0x12 G=0x34 B=0x56 (存储 BGR: 56 34 12)


def main():
    g = GPU(0x43CB0000, verbose=False)
    if not g.probe():
        print("GPU 不存在"); return

    # 在 (100,100) 写一个 40x40 的特征色块
    g.clear_error()
    g.wr(0x08, FB_PHYS); g.wr(0x0C, STRIDE)
    g.wr(0x10, (100 << 16) | 100)
    g.wr(0x14, (139 << 16) | 139)
    g.wr(0x18, PATTERN)
    g.wr(0x04, 0)
    g.wr(0x00, 1)
    time.sleep(0.5)
    n = g.rd(0x1C)
    print("GPU 报告写了 %d 像素, STATUS=0x%X" % (n, g.rd(0x20)))

    # 目标位置应该是什么
    want = bytes([0x56, 0x34, 0x12])
    print("期望写入的字节: %s" % want.hex())

    # 先看目标地址
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    off = FB_PHYS + 100 * STRIDE + 100 * 3
    m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=off & ~4095)
    got = m[(off & 4095):(off & 4095) + 3]
    m.close()
    print("显存 (100,100) 处实际字节: %s  %s" %
          (got.hex(), "← 相同!" if got == want else "← 不同"))

    # 扫低端 DDR 找这个模式
    print("")
    print("扫描内存找这个颜色...")
    found = []
    for base, length, name in ((0x00000000, 0x10000000, "低端 256MB"),
                               (0x10000000, 0x10000000, "中端 256MB"),
                               (0x20000000, 0x10000000, "高端 256MB"),
                               (0x30000000, 0x10000000, "CMA/顶部 256MB")):
        CH = 1 << 20
        o = 0
        while o < length and len(found) < 6:
            try:
                m = mmap.mmap(fd, min(CH, length - o), mmap.MAP_SHARED,
                              mmap.PROT_READ, offset=base + o)
                i = m.find(want)
                if i >= 0:
                    addr = base + o + i
                    # 看是不是连续的 3 的倍数(说明是像素)
                    found.append((addr, name))
                    print("  ★ 在 0x%08X 找到 (%s)" % (addr, name))
                m.close()
            except Exception as ex:
                pass
            o += CH
    os.close(fd)
    if not found:
        print("  没找到 —— 说明 GPU 的写根本没进 DDR")
    g.close()


main()
