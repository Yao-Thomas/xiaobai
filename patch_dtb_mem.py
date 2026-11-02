#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_dtb_mem.py —— 给设备树 bootargs 加 mem=（预留内存给 PL）

════════════════════════════════════════════════════════════════════
为什么
════════════════════════════════════════════════════════════════════
CNN 的 m_axi 挂在 S_AXI_HP3 上，只能访问 DDR（用不了片内 OCM）。
用户态要拿一块【不可缓存、且没有缓存别名】的 DDR，正规做法是
开机就把一段内存从 Linux 手里扣掉（bootargs 的 mem=），
然后只用 /dev/mem 去映射它 —— 没有匿名 mmap 做别名，
就不存在"同一物理页两种 cache 属性"这个未定义行为。

实测依据：现在用"匿名 mmap 占位 + /dev/mem 再映射一份"的办法，
探针能过 13/13、conv1 连过 8 次 100%，但仍有 ~6% 随机错误，
同一组数据跑 10 次会 98.7% → 100% → 90.2% 地漂。

════════════════════════════════════════════════════════════════════
做法：等长替换
════════════════════════════════════════════════════════════════════
DTB 里的属性值是"长度 + 数据"，改长度就要动一堆偏移，容易弄坏，
而 DTB 坏了板子起不来（远程只能插 SD 卡救）。

所以挑一段【等长】的：
    rootwait earlycon   (17 字符)
 -> rootwait mem=992M   (17 字符)

⇒ 整个 DTB 大小、头部字段、所有偏移【一个字节都不变】。

992M = 1024M - 32M，即把 0x3E000000~0x3FFFFFFF（32MB）留给 PL。
earlycon 只是早期串口调试输出，正常运行不需要。

用法:
    python patch_dtb_mem.py in.dtb out.dtb
    python patch_dtb_mem.py in.dtb --check
    python patch_dtb_mem.py in.dtb out.dtb --mem 1008M   # 换预留大小
"""
import argparse
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DT_MAGIC = 0xd00dfeed


def hdr(b):
    f = struct.unpack(">10I", b[:40])
    if f[0] != DT_MAGIC:
        raise ValueError("不是有效 DTB（magic=0x%08X）" % f[0])
    return {"totalsize": f[1], "off_struct": f[2], "off_strings": f[3],
            "size_strings": f[8], "size_struct": f[9], "version": f[5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?", default="")
    ap.add_argument("--mem", default="992M")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    orig = open(a.src, "rb").read()
    b = bytearray(orig)
    h = hdr(orig)

    print("=" * 70)
    print(" 设备树 bootargs 加 mem=")
    print("=" * 70)
    print(" 文件      : %s (%d 字节)" % (a.src, len(orig)))
    print(" totalsize: %d" % h["totalsize"])
    print(" struct   : off=%d size=%d" % (h["off_struct"], h["size_struct"]))
    print()

    # 找 bootargs 字符串
    idx = orig.find(b"console=ttyPS0")
    if idx < 0:
        print(" ★ 没找到 console=ttyPS0")
        return 1
    end = orig.find(b"\x00", idx)
    bootargs = orig[idx:end].decode("latin-1")
    print(" bootargs @%d:" % idx)
    print("   %r" % bootargs)
    print()

    # ── 等长替换 ──
    old = b"rootwait earlycon"
    new = ("rootwait mem=" + a.mem).encode("latin-1")
    if len(old) != len(new):
        print(" ★ 长度不等：%r(%d) vs %r(%d)"
              % (old.decode(), len(old), new.decode(), len(new)))
        return 1

    if b"rootwait earlycon" not in orig:
        if b"mem=" in orig[idx:end]:
            print(" 已经有 mem= 了，不用改")
            return 0
        print(" ★ 没找到 'rootwait earlycon'，无法做等长替换")
        print("   现有 bootargs：%r" % bootargs)
        return 1

    n = 0
    i = 0
    while True:
        j = b.find(old, i)
        if j < 0:
            break
        b[j:j + len(old)] = new
        n += 1
        i = j + len(new)
    print(" 替换 %d 处：%r -> %r （各 %d 字符）"
          % (n, old.decode(), new.decode(), len(old)))

    newend = b.find(b"\x00", idx)
    print(" 新 bootargs  ：%r" % bytes(b[idx:newend]).decode("latin-1"))
    print()

    # ── 校验 ──
    h2 = hdr(bytes(b))
    same = all(h[k] == h2[k] for k in h)
    print(" 校验:")
    print("   大小不变      : %s (%d == %d)"
          % ("✓" if len(b) == len(orig) else "✗", len(b), len(orig)))
    print("   头部字段不变  : %s" % ("✓" if same else "✗"))
    print("   magic 仍是 dtb: %s"
          % ("✓" if struct.unpack(">I", b[:4])[0] == DT_MAGIC else "✗"))
    diff = sum(1 for i in range(len(orig)) if orig[i] != b[i])
    print("   改动字节数    : %d（应该刚好等于替换长度 %d）"
          % (diff, n * len(old)))

    if a.check:
        print("\n （--check 模式，不写文件）")
        return 0
    if not a.dst:
        print("\n （没给输出文件名）")
        return 0
    open(a.dst, "wb").write(bytes(b))
    print("\n 已写出: %s" % a.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
