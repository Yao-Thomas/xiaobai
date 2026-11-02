#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gpu_diag.py —— 诊断 GPU 为什么超时

检查:
  1. SLCR 里 PL 复位 / 电平转换器 / AFI 的状态
  2. GPU 寄存器能不能写进去再读回来 (测写通路)
  3. 跑一次填充, 看 STATUS 的错误位
"""
import mmap
import os
import struct
import time

try:
    sys_stdout = None
except Exception:
    pass


def mapreg(addr, size=0x1000):
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(fd, size, mmap.MAP_SHARED,
                  mmap.PROT_READ | mmap.PROT_WRITE, offset=addr)
    return fd, m


def rd(m, off):
    return struct.unpack_from("<I", m, off)[0]


def wr(m, off, v):
    m[off:off + 4] = struct.pack("<I", v & 0xFFFFFFFF)


print("=" * 56)
print("[1] SLCR (系统级控制寄存器) 状态")
print("=" * 56)
fd0, s = mapreg(0xF8000000)
names = [
    (0x240, "FPGA_RST_CTRL  (PL 复位, 0=释放)"),
    (0x244, "FPGA_CTRL      (PL 时钟/电平)"),
    (0x900, "LVL_SHFTR_EN   (PS-PL 电平转换)"),
]
for off, nm in names:
    print("  0x%08X  %-34s = 0x%08X" % (0xF8000000 + off, nm, rd(s, off)))
os.close(fd0)

print()
print("  各 AFI 通道控制 (PL 主机访问 DDR 的通路):")
for base, nm in [(0xF8008000, "AFI0"), (0xF8009000, "AFI1"),
                 (0xF800A000, "AFI2"), (0xF800B000, "AFI3")]:
    fd, m = mapreg(base)
    print("    %s  RD=0x%08X  WR=0x%08X" % (nm, rd(m, 0), rd(m, 4)))
    os.close(fd)

print()
print("=" * 56)
print("[2] GPU 寄存器读写测试 (0x43CB0000)")
print("=" * 56)
fd, g = mapreg(0x43CB0000)
REG = {"CTRL": 0x00, "OP": 0x04, "BASE": 0x08, "STRIDE": 0x0C,
       "XY0": 0x10, "XY1": 0x14, "COLOR": 0x18, "PIXCNT": 0x1C,
       "STATUS": 0x20}
for nm, off in REG.items():
    print("  %-8s +0x%02X = 0x%08X" % (nm, off, rd(g, off)))

print()
print("  写 COLOR=0x00FF8040, 再读回: ", end="")
wr(g, 0x18, 0x00FF8040)
time.sleep(0.05)
back = rd(g, 0x18)
print("0x%08X  %s" % (back, "✅ 写通路正常" if back == 0x00FF8040 else "❌ 写不进去!"))
wr(g, 0x18, 0)

print()
print("=" * 56)
print("[3] 跑一次实际填充, 看 STATUS")
print("=" * 56)
FB = 0x3F100000
print("  BASE=0x%08X  STRIDE=3072  填充 (0,0) 64x64 颜色 0x0000FF00" % FB)
wr(g, 0x08, FB)
wr(g, 0x0C, 3072)
wr(g, 0x10, (0 << 16) | 0)
wr(g, 0x14, (64 << 16) | 64)
wr(g, 0x18, 0x0000FF00)
wr(g, 0x04, 0)                 # OP=0 矩形填充
wr(g, 0x00, 1)                 # CTRL start

t0 = time.time()
done = False
while time.time() - t0 < 3.0:
    st = rd(g, 0x20)
    pc = rd(g, 0x1C)
    if st & 1:
        print("  ❌ STATUS 错误位置位! STATUS=0x%08X  PIXCNT=%d  用时 %.0f ms"
              % (st, pc, (time.time() - t0) * 1000))
        wr(g, 0x20, 1)         # 写1清错误
        break
    if rd(g, 0x00) & 1 == 0:
        done = True
        print("  ✅ 完成! PIXCNT=%d  用时 %.1f ms" % (pc, (time.time() - t0) * 1000))
        break
    time.sleep(0.02)
if not done and not (rd(g, 0x20) & 1):
    print("  ❌ 超时, CTRL=0x%08X PIXCNT=%d STATUS=0x%08X"
          % (rd(g, 0x00), rd(g, 0x1C), rd(g, 0x20)))

os.close(fd)
