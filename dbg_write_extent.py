#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_write_extent.py —— 到底写了多少字节？写到哪去了？

════════════════════════════════════════════════════════════════════
上一个探针的发现
════════════════════════════════════════════════════════════════════
    全 0  输入 → f1 有 68 个非零（应该全 0）
    全 255 输入 → f1 有 68 个 127（应该全 127）
    ⇒ 1352 个输出位置里，只有 68 个"活"着，而且 68 ≈ 一个 cache line

两种可能：
    A. 加速器真的只写了 68 字节（burst/长度问题）
    B. 加速器写了全部，但 CPU 只看到 68 字节（缓存失效没覆盖全）

这个脚本分开测：
    ① 打印非零值的确切下标（连续？周期？）
    ② 反复 invalidate + 读，看会不会变
    ③ 换个方式读：把 fb1 分块、每块前后都 invalidate
    ④ 用 /dev/mem 从物理地址读（绕开 CPU 缓存）
    ⑤ 跑之前先把整个 fb1 填 0x5A，跑完看哪些字节被改了
       （★ 这个最干净：能精确看出被写的范围）

用法:
    sudo python3 dbg_write_extent.py
"""
import mmap
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
PAGE = 4096


def hdr(s):
    print()
    print("─" * 72)
    print(" %s" % s)
    print("─" * 72)


def read_phys(paddr, n):
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    try:
        base = paddr & ~(PAGE - 1)
        off = paddr - base
        m = mmap.mmap(fd, ((off + n + PAGE - 1) // PAGE) * PAGE,
                      mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        try:
            return bytes(m[off:off + n])
        finally:
            m.close()
    finally:
        os.close(fd)


def main():
    import cnn_linux as CL

    print("=" * 72)
    print(" 输出写入范围排查")
    print("=" * 72)

    c = CL.Cnn(verbose=False)
    IH = IW = 28
    MFQ_PROBE = 65536

    # 权重 & 输入：全 255（int8=127），期望 f1 全部 127
    c.w1.write(bytes([1]) * 72)
    c.w1.flush()
    c.img.write(bytes([255]) * (IH * IW))
    c.img.flush()

    # ── ⑤ 先给 fb1 填 0x5A，跑完看哪些字节被改 ──
    hdr("⑤ fb1 预填 0x5A → 跑一次 → 看哪些字节被改了")
    c.fb1.write(bytes([0x5A]) * c.fb1.size)
    c.fb1.flush()
    c.fb1.invalidate()
    before = list(c.fb1.read(c.fb1.size))
    print("  跑之前 fb1 前 16: %s" % [hex(v) for v in before[:16]])
    print("  跑之前都是 0x5A? %s" % all(v == 0x5A for v in before))

    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=MFQ_PROBE)
    c.fb1.invalidate()
    after = list(c.fb1.read(c.fb1.size))
    changed = [i for i in range(len(after)) if after[i] != 0x5A]
    print("  跑之后被改动的字节数 = %d / %d" % (len(changed), len(after)))
    if changed:
        print("  被改动的下标范围: %d .. %d" % (min(changed), max(changed)))
        print("  前 20 个被改的下标: %s" % changed[:20])
        # 连续性
        runs = []
        s = changed[0]
        p = changed[0]
        for i in changed[1:]:
            if i != p + 1:
                runs.append((s, p))
                s = i
            p = i
        runs.append((s, p))
        print("  连续段（前 12 段）: %s" % runs[:12])
        print("  共 %d 段" % len(runs))
    print("  被改位置的值（前 16 个）: %s"
          % [after[i] - 256 if after[i] >= 128 else after[i]
             for i in changed[:16]])

    # ── ① 非零下标 ──
    hdr("① 全 255 输入下的非零下标")
    f = [x - 256 if x >= 128 else x for x in after]
    nz = [i for i, v in enumerate(f) if v != 0]
    print("  非零个数 = %d" % len(nz))
    if nz:
        print("  下标前 24: %s" % nz[:24])
        print("  下标后 8:  %s" % nz[-8:])
        print("  按 [oc][y][x] 解释前 12 个：")
        for i in nz[:12]:
            print("    idx=%4d → oc=%d y=%2d x=%2d  值=%d"
                  % (i, i // 169, (i % 169) // 13, (i % 169) % 13, f[i]))
        print("  按 [y][x][oc] 解释前 12 个：")
        for i in nz[:12]:
            print("    idx=%4d → y=%2d x=%2d oc=%d  值=%d"
                  % (i, i // (13 * 8), (i // 8) % 13, i % 8, f[i]))

    # ── ② 反复 invalidate + 读 ──
    hdr("② 反复 invalidate + 读，看结果稳不稳")
    for k in range(4):
        c.fb1.invalidate()
        v = list(c.fb1.read(16))
        print("  第 %d 次: %s" % (k + 1, v))

    # ── ③ 分块读，每块前后都 invalidate ──
    hdr("③ 分块读（每块 64 字节，前后各 invalidate 一次）")
    counts = []
    for blk in range(0, min(1352, 1408), 64):
        c.fb1.invalidate()
        seg = list(c.fb1.read(min(64, 1352 - blk), blk))
        nzc = sum(1 for x in seg if x != 0)
        counts.append((blk, nzc))
    print("  每 64 字节块里非零个数:")
    for blk, nzc in counts:
        print("    偏移 %4d : %2d 个非零" % (blk, nzc))

    # ── ④ 从物理地址读 ──
    hdr("④ 从 /dev/mem 的物理地址读 fb1（绕开 CPU 缓存）")
    try:
        pv = read_phys(c.fb1.paddr, 64)
        print("  paddr=0x%08X 前 16: %s" % (c.fb1.paddr, list(pv[:16])))
        nzp = sum(1 for x in pv if x != 0)
        print("  前 64 字节里非零 %d 个" % nzp)
    except Exception as ex:
        print("  失败: %s" % ex)

    # ── ⑥ 对照：换个 MFQ，看被写的范围变不变 ──
    hdr("⑥ 换 MFQ=201（正常值）再看一次被写的范围")
    c.fb1.write(bytes([0x5A]) * c.fb1.size)
    c.fb1.flush()
    c.run_cpq(IH, IW, 1, 8, c.img, c.w1, c.fb1, mfq=201)
    c.fb1.invalidate()
    a2 = list(c.fb1.read(c.fb1.size))
    ch2 = [i for i in range(len(a2)) if a2[i] != 0x5A]
    print("  被改动字节数 = %d  范围 %s"
          % (len(ch2), (min(ch2), max(ch2)) if ch2 else "无"))
    if ch2:
        vals = [a2[i] - 256 if a2[i] >= 128 else a2[i] for i in ch2[:16]]
        print("  值（前 16）: %s" % vals)

    c.close()
    print()
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
