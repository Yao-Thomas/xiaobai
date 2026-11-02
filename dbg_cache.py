#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_cache.py —— 查 cache invalidate 到底有没有效，并找出能用的方法

════════════════════════════════════════════════════════════════════
问题
════════════════════════════════════════════════════════════════════
加速器写 DDR → CPU 读回，结果【永远是上一次的】。
⇒ `cacheflush` 系统调用没起作用（或者漏了某级缓存）。

这条也解释了为什么 MNIST 能过、波形不行：
    MNIST 只读一次 logits（cache miss → 从 DDR 取 → 对）
    波形要循环 64 次，从第二次起就读到缓存旧值

测试方法
════════════════════════════════════════════════════════════════════
用 /dev/mem 往「CPU 已缓存的同一物理页」写新数据（模拟加速器写 DDR），
然后试不同的失效方法，看 CPU 能不能看到新数据。

★ 前提：如果 /dev/mem 也是缓存的，这个测试会被污染 —— 所以先测
  /dev/mem 本身是不是缓存的（对照：先 flush 再经 /dev/mem 读）。

方法清单：
    A. 现在的 cacheflush（flags=0）
    B. cacheflush flags=1
    C. cacheflush + 读之前再 flush 一次
    D. msync（对匿名映射无效，试一下）
    E. 重新 mmap 同一物理页（换一个虚拟地址）
    F. 用 ctypes 直接调 __builtin___clear_cache

用法:
    sudo python3 dbg_cache.py
"""
import ctypes
import mmap
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
PAGE = 4096
SYS_cacheflush = 0xf0002
_libc = ctypes.CDLL("libc.so.6", use_errno=True)


def hdr(s):
    print()
    print("─" * 72)
    print(" %s" % s)
    print("─" * 72)


def mem_write(paddr, data):
    """用 /dev/mem 往物理地址写"""
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        base = paddr & ~(PAGE - 1)
        off = paddr - base
        m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        try:
            m[off:off + len(data)] = data
        finally:
            m.close()
    finally:
        os.close(fd)


def mem_read(paddr, n):
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        base = paddr & ~(PAGE - 1)
        off = paddr - base
        m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        try:
            return bytes(m[off:off + n])
        finally:
            m.close()
    finally:
        os.close(fd)


def cf(vaddr, alloc, flags=0):
    """调 cacheflush，返回 (ret, errno)"""
    ctypes.set_errno(0)
    r = _libc.syscall(ctypes.c_long(SYS_cacheflush),
                      ctypes.c_void_p(vaddr),
                      ctypes.c_void_p(vaddr + alloc),
                      ctypes.c_int(flags))
    return r, ctypes.get_errno()


def main():
    import cnn_linux as CL

    print("=" * 72)
    print(" cache 失效方法排查")
    print("=" * 72)

    b = CL.DmaBuf(64, "probe")
    print("  测试缓冲: vaddr=0x%X  paddr=0x%08X  alloc=%d"
          % (b.vaddr, b.paddr, b.alloc))

    # ── 0. cacheflush 返回值 ──
    hdr("0) cacheflush 系统调用返回值")
    for fl in (0, 1, 2):
        r, e = cf(b.vaddr, b.alloc, fl)
        print("   flags=%d → ret=%d errno=%d %s"
              % (fl, r, e, "(errno=%d: %s)" % (e, os.strerror(e)) if e else "OK"))

    # ── 1. /dev/mem 是不是缓存的 ──
    hdr("1) /dev/mem 本身是不是缓存的")
    b.write(b"\x11" * 64)
    b.flush()
    time.sleep(0.01)
    v1 = mem_read(b.paddr, 8)
    print("  CPU 写 0x11 → cacheflush → /dev/mem 读到 %s" % list(v1))
    print("   %s" % ("✓ /dev/mem 能看到 DDR（不缓存，或已同步）"
                     if v1[0] == 0x11 else "★ 不一致"))

    # ── 2. 核心测试：模拟"加速器写 DDR" ──
    hdr("2) 核心测试：/dev/mem 写新值（模拟加速器）→ 各方法读回")
    results = {}

    for name, method in (
        ("A 不 flush 直接读", None),
        ("B cacheflush(0)", lambda: cf(b.vaddr, b.alloc, 0)),
        ("C cacheflush(1)", lambda: cf(b.vaddr, b.alloc, 1)),
        ("D cacheflush(0)×3", lambda: [cf(b.vaddr, b.alloc, 0) for _ in range(3)]),
        ("E msync", lambda: b.buf.flush()),
    ):
        # 先让 CPU 缓存里有一份旧值
        b.write(b"\x11" * 64)
        b.flush()
        _ = b.read(8)                       # ★ 把旧值读进缓存
        # 从 /dev/mem 写新值（模拟加速器写 DDR）
        mem_write(b.paddr, b"\x22" * 64)
        # 用该方法
        if method:
            try:
                method()
            except Exception as e:
                print("   %-22s 方法抛错: %s" % (name, e))
                continue
        got = b.read(8)
        results[name] = got[0]
        print("   %-22s 读到 0x%02X  %s"
              % (name, got[0],
                 "✓ 看到了新值 0x22" if got[0] == 0x22
                 else "★ 还是旧值 0x11（失效没生效）"))

    # ── 3. 换个虚拟地址重新映射同一物理页 ──
    hdr("3) 方法 F：重新 mmap 同一物理页（换虚拟地址）")
    b.write(b"\x11" * 64)
    b.flush()
    _ = b.read(8)
    mem_write(b.paddr, b"\x33" * 64)
    try:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        base = b.paddr & ~(PAGE - 1)
        off = b.paddr - base
        m2 = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        got2 = bytes(m2[off:off + 8])
        m2.close()
        os.close(fd)
        print("   经新映射读到: %s  %s"
              % (list(got2),
                 "✓ 是新值 0x33" if got2[0] == 0x33 else "★ 还是 0x%02X" % got2[0]))
        results["F 新 mmap"] = got2[0]
    except Exception as e:
        print("   失败: %s" % e)

    # ── 4. 用 __clear_cache ──
    hdr("4) 方法 G：libgcc 的 __clear_cache")
    try:
        libgcc = ctypes.CDLL("libgcc_s.so.1")
        if hasattr(libgcc, "__clear_cache"):
            b.write(b"\x11" * 64); b.flush(); _ = b.read(8)
            mem_write(b.paddr, b"\x44" * 64)
            libgcc.__clear_cache(ctypes.c_void_p(b.vaddr),
                                 ctypes.c_void_p(b.vaddr + b.alloc))
            got = b.read(8)
            print("   读到 0x%02X  %s" % (got[0],
                  "✓ 新值" if got[0] == 0x44 else "★ 旧值"))
            results["G __clear_cache"] = got[0]
        else:
            print("   libgcc_s 里没有 __clear_cache")
    except Exception as e:
        print("   失败: %s" % e)

    # ── 5. 结论 ──
    hdr("5) 结论")
    good = [k for k, v in results.items() if v == 0x22 or v == 0x33 or v == 0x44]
    for k, v in results.items():
        print("   %-24s 读到 0x%02X  %s" % (k, v, "✓" if k in good else "✗"))
    print()
    if good:
        print("   ★ 能用的方法: %s" % ", ".join(good))
    else:
        print("   ★ 所有方法都没生效 —— 需要换思路（比如让缓冲本身不可缓存）")

    b.close()
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
