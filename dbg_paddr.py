#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_paddr.py —— 验证 DmaBuf 的物理地址到底对不对（板子上 sudo 跑）

════════════════════════════════════════════════════════════════════
为什么要查这个
════════════════════════════════════════════════════════════════════
探针实验（dbg_layout_probe.py 探针 1）：
    输入是【常数图】，权重每通道一个常数
    ⇒ 每个通道的输出应该在所有位置都一样
    实际却出现 24 种杂乱的值，还有 946 个 0
    ⇒ 硬件读到的【不是我们写进去的那张图】

那要么是
    A. pagemap 翻译出来的物理地址是错的（CPU 和加速器看的不是同一块内存）
    B. IP 的 m_axi 地址映射有偏移（IP 眼里的地址 ≠ 物理地址）

这个脚本查 A：
    往 DmaBuf 写一个魔数 → 从 /dev/mem 的 paddr 读回来 → 应该一模一样
    再扫附近的物理地址，看数据是不是跑别处去了

用法:
    sudo python3 dbg_paddr.py
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


def hdr(s):
    print()
    print("─" * 70)
    print(" %s" % s)
    print("─" * 70)


def read_phys(paddr, n):
    """从 /dev/mem 读 n 字节"""
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        base = paddr & ~(PAGE - 1)
        off = paddr - base
        m = mmap.mmap(fd, PAGE + ((off + n + PAGE - 1) // PAGE) * PAGE,
                      mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        try:
            return m[off:off + n]
        finally:
            m.close()
    finally:
        os.close(fd)


def main():
    import cnn_linux as CL

    print("=" * 70)
    print(" DmaBuf 物理地址验证")
    print("=" * 70)

    c = CL.Cnn(verbose=False)

    # ── 1. pagemap 能不能读出 PFN ──
    hdr("1) pagemap 可读性")
    try:
        with open("/proc/self/pagemap", "rb") as f:
            f.seek(((c.img.vaddr) // PAGE) * 8)
            e = struct.unpack("<Q", f.read(8))[0]
        print("  img 的 pagemap 项 = 0x%016X" % e)
        print("   present(bit63) = %d" % ((e >> 63) & 1))
        print("   PFN(bits0-54)  = 0x%X" % (e & ((1 << 55) - 1)))
        print("   换算物理地址   = 0x%08X" % ((e & ((1 << 55) - 1)) * PAGE))
        print("   DmaBuf 算出来的 = 0x%08X" % c.img.paddr)
        print("   %s" % ("✓ 一致" if ((e & ((1 << 55) - 1)) * PAGE) == c.img.paddr
                         else "★ 不一致！"))
        if (e & ((1 << 55) - 1)) == 0:
            print("   ★★ PFN 是 0 —— 内核没给 PFN（缺 CAP_SYS_ADMIN？）")
    except Exception as ex:
        print("  读 pagemap 失败: %s" % ex)

    # ── 2. 写魔数 → 从 /dev/mem 读回 ──
    hdr("2) 每个缓冲：写入魔数 → 从 /dev/mem 的 paddr 读回")
    for nm in ("img", "w1", "fb1", "w2", "fb2", "wf", "lg"):
        b = getattr(c, nm)
        n = min(64, b.size)
        magic = bytes([(0x40 + i) & 0xFF for i in range(n)])
        b.write(magic)
        b.flush()
        try:
            back = read_phys(b.paddr, n)
            same = (back == magic)
            print("  %-4s paddr=0x%08X  %s" % (nm, b.paddr,
                  "✓ 一致" if same else "★ 不一致"))
            if not same:
                print("       写入: %s" % magic[:16].hex(" "))
                print("       读回: %s" % back[:16].hex(" "))
        except Exception as ex:
            print("  %-4s paddr=0x%08X  读 /dev/mem 失败: %s"
                  % (nm, b.paddr, ex))

    # ── 3. 数据是不是跑到别的物理地址去了 ──
    hdr("3) 在 img 的 paddr 附近扫，看魔数在不在别处")
    b = c.img
    magic = bytes([(0x40 + i) & 0xFF for i in range(16)])
    b.write(magic)
    b.flush()
    found = []
    base = b.paddr
    for delta in range(-16 * PAGE, 17 * PAGE, PAGE):
        p = base + delta
        if p < 0:
            continue
        try:
            v = read_phys(p, 16)
            if v == magic:
                found.append(delta)
        except Exception:
            pass
    print("  在 paddr 偏移 %s 处找到了相同内容"
          % ([d // PAGE for d in found] or "无（只有 0）"))
    print("  ★ 只应该在偏移 0 处找到")

    # ── 4. 反向验证：从 /dev/mem 写，看 CPU 能不能看到 ──
    hdr("4) 从 /dev/mem 往 fb1 写，看 CPU 读 DmaBuf 能不能看到")
    b = c.fb1
    pat = bytes([0xA5] * 16)
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        base = b.paddr & ~(PAGE - 1)
        off = b.paddr - base
        m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        m[off:off + 16] = pat
        m.flush()
        m.close()
        os.close(fd)
        b.invalidate()
        got = b.read(16)
        print("  /dev/mem 写入: %s" % pat.hex(" "))
        print("  DmaBuf 读到:   %s" % got.hex(" "))
        print("  %s" % ("✓ 一致（paddr 是对的）" if got == pat
                         else "★ 不一致（paddr 有问题）"))
    except Exception as ex:
        print("  失败: %s" % ex)

    # ── 5. 缓冲之间有没有重叠 ──
    hdr("5) 各缓冲的物理区间有没有重叠")
    rng = []
    for nm in ("img", "w1", "fb1", "w2", "fb2", "wf", "lg"):
        bb = getattr(c, nm)
        rng.append((bb.paddr, bb.paddr + bb.alloc, nm))
    rng.sort()
    bad = False
    for i in range(len(rng) - 1):
        if rng[i][1] > rng[i + 1][0]:
            print("  ★ 重叠: %s [0x%08X,0x%08X) 与 %s [0x%08X,...)"
                  % (rng[i][2], rng[i][0], rng[i][1],
                     rng[i + 1][2], rng[i + 1][0]))
            bad = True
    if not bad:
        print("  ✓ 没有重叠")
    for a, b2, nm in rng:
        print("    %-4s [0x%08X, 0x%08X)" % (nm, a, b2))

    c.close()
    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
