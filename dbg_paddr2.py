#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_paddr2.py —— 干净地定位物理地址错位（板子上 sudo 跑）

上一个脚本（dbg_paddr.py）的毛病：每个缓冲写的魔数【一模一样】，
所以"读回 == 写入"说明不了是哪个缓冲的数据。

这次：
    img 写 0xAA…
    w1  写 0xBB…
    fb1 写 0xCC…
    ⇒ 读回一看就知道是哪块的数据跑哪去了

而且把【虚拟地址】也打出来，看是不是 vaddr/paddr 的对应关系错位。

用法:
    sudo python3 dbg_paddr2.py
"""
import ctypes
import mmap
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
PAGE = 4096


def read_phys(paddr, n):
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        base = paddr & ~(PAGE - 1)
        off = paddr - base
        m = mmap.mmap(fd, PAGE * 2, mmap.MAP_SHARED, mmap.PROT_READ,
                      offset=base)
        try:
            return m[off:off + n]
        finally:
            m.close()
    finally:
        os.close(fd)


def main():
    import cnn_linux as CL

    print("=" * 72)
    print(" 物理地址错位定位（每块写不同的模式）")
    print("=" * 72)

    c = CL.Cnn(verbose=False)

    tags = {"img": 0xAA, "w1": 0xBB, "fb1": 0xCC, "w2": 0xDD,
            "fb2": 0xEE, "wf": 0x11, "lg": 0x22}

    print()
    print("① 虚拟地址 / 物理地址对照")
    print("   %-5s %-16s %-16s %s" % ("缓冲", "vaddr", "paddr", "页内偏移"))
    for nm in tags:
        b = getattr(c, nm)
        print("   %-5s 0x%012X   0x%08X       %d"
              % (nm, b.vaddr, b.paddr, b.vaddr % PAGE))

    print()
    print("② 每块写不同模式并 flush")
    for nm, t in tags.items():
        b = getattr(c, nm)
        n = min(32, b.size)
        pat = bytes([t]) * n
        b.write(pat)
        b.flush()
    print("   img=0xAA*32  w1=0xBB*32  fb1=0xCC*32  w2=0xDD*32")
    print("   fb2=0xEE*32  wf=0x11*32  lg=0x22*32")

    print()
    print("③ 从各自声明的 paddr 读回")
    print("   %-5s %-12s %-10s %s" % ("缓冲", "paddr", "首字节", "判断"))
    for nm, t in tags.items():
        b = getattr(c, nm)
        try:
            got = read_phys(b.paddr, 8)
            first = got[0] if got else -1
            if first == t:
                verdict = "✓ 就是它自己的数据"
            elif first in tags.values():
                owner = [k for k, v in tags.items() if v == first]
                verdict = "★ 这里是 %s 的数据!" % owner[0]
            else:
                verdict = "★ 别人的数据 (0x%02X: %r)" % (first, got[:12])
            print("   %-5s 0x%08X   0x%02X       %s"
                  % (nm, b.paddr, first, verdict))
        except Exception as ex:
            print("   %-5s 0x%08X   读取失败: %s" % (nm, b.paddr, ex))

    print()
    print("④ 扫 img.paddr 前后 4 页，找 0xAA")
    b = c.img
    for d in range(-4, 5):
        p = b.paddr + d * PAGE
        if p < 0:
            continue
        try:
            got = read_phys(p, 8)
            f = got[0] if got else -1
            who = {v: k for k, v in tags.items()}.get(f, "?")
            print("   偏移 %+d 页  0x%08X  首字节 0x%02X  %s"
                  % (d, p, f, ("← ★ img 的数据在这" if f == 0xAA else "")))
        except Exception as ex:
            print("   偏移 %+d 页  0x%08X  失败: %s" % (d, p, ex))

    print()
    print("⑤ 用 mmap 直接确认 vaddr 处的数据（不经 /dev/mem）")
    for nm in ("img", "w1"):
        b = getattr(c, nm)
        b.invalidate()
        v = b.read(8)
        print("   %-4s buf[0:8] = %s  %s"
              % (nm, v.hex(" "), "✓" if v[0] == tags[nm] else "★ 不对"))

    print()
    print("⑥ 逐页查 pagemap 原始项（看 PFN 是不是读错了）")
    for nm in ("img", "w1", "fb1"):
        b = getattr(c, nm)
        with open("/proc/self/pagemap", "rb") as f:
            f.seek((b.vaddr // PAGE) * 8)
            e = struct.unpack("<Q", f.read(8))[0]
        pfn = e & ((1 << 55) - 1)
        print("   %-4s va=0x%012X  项=0x%016X  PFN=0x%X  pfn*4096=0x%08X  "
              "DmaBuf.paddr=0x%08X  %s"
              % (nm, b.vaddr, e, pfn, pfn * PAGE, b.paddr,
                 "✓" if pfn * PAGE == b.paddr else "★ 不一致"))

    c.close()
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
