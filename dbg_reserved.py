#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_reserved.py —— 验证预留区（0x3E000000）能不能当干净的 DMA 缓冲

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
之前用"匿名 mmap 占位 + /dev/mem 再映射一份"的办法，两个映射同页
不同 cache 属性，实测有 ~6% 的随机错误。

现在 bootargs 加了 mem=992M，0x3E000000~0x3FFFFFFF（32MB）已经
从 Linux 手里扣掉 —— 这块内存【只有一个映射】，就是 /dev/mem 那份。

要验的就是：
    ① 能不能读写
    ② 读写稳不稳（特别是"跑一次加速器之后再读"）
    ③ 有没有缓存问题（CPU 写入后，从第二个映射读是不是立刻能看到）

用法:
    sudo python3 dbg_reserved.py
"""
import mmap
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = 0x3E000000
SIZE = 0x02000000          # 32MB
PAGE = 4096


def hdr(s):
    print()
    print("─" * 70)
    print(" %s" % s)
    print("─" * 70)


def main():
    print("=" * 70)
    print(" 预留区验证（0x%08X，%d MB）" % (BASE, SIZE >> 20))
    print("=" * 70)

    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)

    # ── ① 基本读写 ──
    hdr("① 基本读写")
    try:
        m = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
    except Exception as e:
        print("  ✗ 映射失败: %s" % e)
        os.close(fd)
        return 1
    pat = bytes([0xA5] * 64)
    m[0:64] = pat
    time.sleep(0.01)
    got = bytes(m[0:64])
    print("  写 0xA5×64 -> 读回 %s  %s"
          % (got[:8].hex(" "), "✓" if got == pat else "✗"))
    m.close()

    # ── ② 换一个新的映射，看能不能立刻看到（验证不可缓存）──
    hdr("② 换个新映射读同一地址（如果缓存了会读到旧值）")
    m1 = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
    m1[0:16] = bytes([0x11] * 16)
    _ = bytes(m1[0:16])                     # 让 CPU 缓存里有一份
    # 从另一个映射写新值
    m2 = mmap.mmap(fd, PAGE, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
    m2[0:16] = bytes([0x22] * 16)
    time.sleep(0.005)
    r1 = bytes(m1[0:16])
    r2 = bytes(m2[0:16])
    print("  m1 写 0x11 → m2 写 0x22 → 读回:")
    print("    m1: %s" % r1[:8].hex(" "))
    print("    m2: %s" % r2[:8].hex(" "))
    print("  %s" % ("✓ 都是 0x22（没缓存问题）" if r1[0] == 0x22 and r2[0] == 0x22
                    else "★ 读到了旧值 —— 有缓存问题"))
    m1.close()
    m2.close()

    # ── ③ 用加速器写，看读回稳不稳 ──
    hdr("③ 用加速器（conv1）写这块内存，连跑 10 次看读回稳不稳")
    sys.path.insert(0, "/home/zynq")
    try:
        import cnn_linux as CL
    except Exception as e:
        print("  import cnn_linux 失败: %s" % e)
        os.close(fd)
        return 1

    wb = open("/home/zynq/wave_weights.bin", "rb").read()
    rin = open("/home/zynq/wave_reference_in.bin", "rb").read()

    # ★ 直接在这块预留区上手工布局（不用 DmaBuf）
    OFF = {"img": 0x000000, "w1": 0x001000, "fb1": 0x002000,
           "w2": 0x004000, "fb2": 0x005000, "wf": 0x006000,
           "lg": 0x00A000}

    def mapbuf(name, size):
        off = BASE + OFF[name]
        mm = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=off)
        return mm, off

    bufs = {}
    for k in OFF:
        bufs[k] = mapbuf(k, 4096)[0]

    def w(k, data, off=0):
        bufs[k][off:off + len(data)] = data

    def r(k, n, off=0):
        return bytes(bufs[k][off:off + n])

    print("  缓冲布局（都在预留区里）:")
    for k, v in OFF.items():
        print("    %-4s @ 0x%08X" % (k, BASE + v))

    # 写权重和输入
    w("w1", wb[0x0000:0x0000 + 72] + b"\x00" * (4096 - 72))
    w("w2", wb[0x0080:0x0080 + 1152] + b"\x00" * (4096 - 1152))
    w("wf", wb[0x0500:0x0500 + 3200] + b"\x00" * (4096 - 3200))
    img = rin[0:784]
    w("img", img + b"\x00" * (4096 - 784))

    # ★ 这里需要 cnn_linux 的 HlsIp 来驱动，但它内部用 DmaBuf。
    #   简单起见：临时把 DmaBuf 换成"直接用这块预留区"的薄封装
    import importlib
    importlib.reload(CL)

    # 用一个假的 DmaBuf 顶替
    class FakeBuf(object):
        def __init__(self, mm, paddr, size, name=""):
            self.mm = mm
            self.paddr = paddr
            self.size = size
            self.name = name

        def write(self, data, off=0):
            self.mm[off:off + len(data)] = data

        def read(self, n, off=0):
            return bytes(self.mm[off:off + n])

        def flush(self):
            pass

        def invalidate(self):
            pass

        def close(self):
            pass

    c = CL.Cnn.__new__(CL.Cnn)
    c.v = False
    c.cpq = CL.HlsIp(CL.CPQ_BASE, "cnn_conv_pool_q")
    c.fcq = CL.HlsIp(CL.FCQ_BASE, "cnn_fc_q")
    c.img = FakeBuf(bufs["img"], BASE + OFF["img"], 4096, "img")
    c.w1 = FakeBuf(bufs["w1"], BASE + OFF["w1"], 4096, "w1")
    c.fb1 = FakeBuf(bufs["fb1"], BASE + OFF["fb1"], 4096, "fb1")
    c.w2 = FakeBuf(bufs["w2"], BASE + OFF["w2"], 4096, "w2")
    c.fb2 = FakeBuf(bufs["fb2"], BASE + OFF["fb2"], 4096, "fb2")
    c.wf = FakeBuf(bufs["wf"], BASE + OFF["wf"], 4096, "wf")
    c.lg = FakeBuf(bufs["lg"], BASE + OFF["lg"], 4096, "lg")

    # CPU 参考
    import waveform_ai as WA
    img_i8 = [x - 256 if x >= 128 else x for x in img]
    W1i = [x - 256 if x >= 128 else x for x in wb[0:72]]
    W2i = [x - 256 if x >= 128 else x for x in wb[0x80:0x80 + 1152]]
    WFi = [x - 256 if x >= 128 else x for x in wb[0x500:0x500 + 3200]]
    f1_cpu, f2_cpu, lg_cpu = CL.cpu_reference(
        img_i8, W1i, W2i, WFi, mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2,
        mfqfc=CL.MFQ_FC, fco=8)

    print()
    print("  连跑 10 次完整链路（conv1→conv2→fc），每次与 CPU 比:")
    print("    次   f1           f2           logits")
    print("    " + "-" * 56)
    for k in range(10):
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        f1 = [x - 256 if x >= 128 else x for x in c.fb1.read(1352)]
        f2 = [x - 256 if x >= 128 else x for x in c.fb2.read(400)]
        lg = [x - 256 if x >= 128 else x for x in c.lg.read(8)]
        s1 = sum(1 for i in range(1352) if f1[i] == f1_cpu[i])
        s2 = sum(1 for i in range(400) if f2[i] == f2_cpu[i])
        ok = "✓" if lg == lg_cpu else "✗"
        print("    %2d   %4d/1352    %3d/400     %s %s"
              % (k + 1, s1, s2, lg, ok))

    print()
    print("  CPU 参考 logits: %s" % lg_cpu)

    for b in bufs.values():
        b.close()
    c.cpq.close()
    c.fcq.close()
    os.close(fd)
    print()
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
