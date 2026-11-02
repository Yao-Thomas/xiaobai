#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_fb_phys.py —— 找出 framebuffer 在 DDR 里的【物理地址】
  背景: DRM 的 fbdev 模拟不填 smem_start, 所以 FBIOGET_FSCREENINFO 返回 0。
        GPU 要写显存就必须知道物理地址。
  做法: 往 /dev/fb0 写一段唯一图案, 然后在 /dev/mem 里搜它。
用法: sudo python3 find_fb_phys.py
"""
import mmap, os, struct, sys, time

FB = "/dev/fb0"
W, H, STRIDE = 1024, 600, 3072
VIRT_H = 1200                      # fb 的虚拟高度(两页)

# 唯一图案: 32 字节, 不太可能偶然出现
PAT = bytes([0xA5, 0x5A, 0xC3, 0x3C, 0x96, 0x69, 0xF0, 0x0F]) * 4


def write_pattern():
    fd = os.open(FB, os.O_RDWR)
    mm = mmap.mmap(fd, STRIDE * VIRT_H, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE)
    mm[0:len(PAT)] = PAT
    mm.flush()
    # 顺便在中间也放一份(防止有偏移)
    mid = STRIDE * 300
    mm[mid:mid + len(PAT)] = PAT
    mm.flush()
    mm.close()
    os.close(fd)
    print("已向 /dev/fb0 写入特征图案 (偏移 0 和 %d)" % mid)
    return mid


def search(base, length, pat, chunk=1 << 20):
    """在 [base, base+length) 里搜 pat, 返回物理地址或 None"""
    fdm = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    off = 0
    try:
        while off < length:
            n = min(chunk, length - off)
            try:
                m = mmap.mmap(fdm, n, mmap.MAP_SHARED, mmap.PROT_READ,
                              offset=base + off)
            except Exception as ex:
                print("  mmap 0x%08X 失败: %s" % (base + off, ex))
                off += n
                continue
            i = m.find(pat)
            m.close()
            if i >= 0:
                return base + off + i
            off += n
    finally:
        os.close(fdm)
    return None


def main():
    mid = write_pattern()

    print("")
    print("=== 搜索物理内存 ===")
    regions = [
        ("CMA 区 (0x3F000000, 16MB)", 0x3F000000, 0x01000000),
        ("低端 DDR (0x10000000, 256MB)", 0x10000000, 0x10000000),
        ("高端 DDR (0x20000000, 512MB)", 0x20000000, 0x20000000),
    ]
    found = None
    for name, base, length in regions:
        t0 = time.time()
        r = search(base, length, PAT)
        dt = time.time() - t0
        if r is not None:
            print("  [%s] 找到! 物理地址 = 0x%08X  (%.1fs)" % (name, r, dt))
            found = r
            break
        else:
            print("  [%s] 未找到 (%.1fs)" % (name, dt))

    print("")
    if found is None:
        print(">>> 没找到, 显存可能不在普通 DDR 里")
        return
    print("=" * 60)
    print(" 显存物理基址 = 0x%08X" % found)
    print("=" * 60)

    # 校验: 读物理地址处的值, 应与图案一致
    fdm = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(fdm, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=found & ~4095)
    off = found & 4095
    got = m[off:off + len(PAT)]
    m.close()
    os.close(fdm)
    print("回读校验: %s" % ("✅ 图案一致" if got == PAT else "❌ 不一致 %s" % got.hex()))

    # 写出结果供 GPU 使用
    with open("/home/zynq/.fb_phys", "w") as f:
        f.write("0x%08X\n" % found)
    print("已写入 /home/zynq/.fb_phys")


main()
