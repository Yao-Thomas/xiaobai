#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_gpu_driver.py —— gpu.py 驱动的单元测试 (不需要硬件!)
  用"模拟寄存器"验证驱动写下的每个寄存器值、位打包、握手、错误处理。
  能在 GPU bitstream 做出来之前就发现驱动 bug。
用法: python test_gpu_driver.py
"""
import os, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gpu import GPU

REG = {0x00: "CTRL", 0x04: "OP", 0x08: "BASE", 0x0C: "STRIDE",
       0x10: "XY0", 0x14: "XY1", 0x18: "COLOR", 0x1C: "PIXCNT", 0x20: "STATUS"}


class MockRegs:
    """模拟 GPU 的 AXI-Lite 寄存器组
       特性: 写 CTRL[0]=1 后立即完成, 并按当前配置算出 PIXCNT"""
    def __init__(self):
        self.buf = bytearray(4096)
        self.writes = []          # [(off, val)]
        self.err = False          # True 则报告总线错误
        self.respond = True       # False 则永不完成(测超时)

    # ---- 驱动用切片写 ----
    def __setitem__(self, k, v):
        self.buf[k] = v
        if isinstance(k, slice) and (k.stop - k.start) == 4:
            off = k.start
            val = struct.unpack("<I", bytes(v))[0]
            self.writes.append((off, val))
            if off == 0x00 and (val & 1) and self.respond:
                self._complete()

    def __getitem__(self, k):
        return self.buf[k]

    def close(self):
        pass

    # ---- 辅助 ----
    def get(self, off):
        return struct.unpack("<I", bytes(self.buf[off:off + 4]))[0]

    def set(self, off, val):
        self.buf[off:off + 4] = struct.pack("<I", val)

    def _complete(self):
        # 按寄存器算出这次要写多少像素
        x0 = self.get(0x10) >> 16
        y0 = self.get(0x10) & 0xFFFF
        x1 = self.get(0x14) >> 16
        y1 = self.get(0x14) & 0xFFFF
        op = self.get(0x04)
        if op == 0:                              # FILL
            px = max(0, x1 - x0 + 1) * max(0, y1 - y0 + 1)
        else:                                    # LINE
            px = max(abs(x1 - x0), abs(y1 - y0)) + 1
        self.set(0x1C, px)
        self.set(0x00, 1)                        # done
        self.set(0x20, 1 if self.err else 0)     # STATUS

    def last(self, off):
        for o, v in reversed(self.writes):
            if o == off:
                return v
        return None


fails = []


def chk(cond, msg):
    if cond:
        print("  ✅ " + msg)
    else:
        print("  ❌ " + msg)
        fails.append(msg)


def main():
    print("=" * 66)
    print(" gpu.py 驱动单元测试 (模拟寄存器)")
    print("=" * 66)

    # ---------- 1. 探测 ----------
    print("\n[1] probe() 探测")
    m = MockRegs()
    g = GPU(verbose=False, mem=m)
    # 模拟寄存器回读 = 写什么读什么
    chk(g.probe(), "probe 返回 True (寄存器可回读)")
    chk(m.get(0x18) == 0x5A5A5A, "probe 写入了 COLOR=0x5A5A5A")

    # ---------- 2. FILL 寄存器序列 ----------
    print("\n[2] fill() 寄存器写入")
    m = MockRegs()
    g = GPU(verbose=False, mem=m)
    n, ok = g.fill(base=0x3F100000, stride=3072, x0=10, y0=20, w=100, h=50,
                   color=0xFF8800)
    chk(m.last(0x08) == 0x3F100000, "BASE = 0x3F100000")
    chk(m.last(0x0C) == 3072, "STRIDE = 3072")
    chk(m.last(0x10) == ((10 << 16) | 20), "XY0 = (x0=10, y0=20) 位打包正确")
    chk(m.last(0x14) == ((109 << 16) | 69), "XY1 = (x0+w-1=109, y0+h-1=69)")
    chk(m.last(0x18) == 0xFF8800, "COLOR = 0xFF8800")
    chk(m.last(0x04) == 0, "OP = 0 (FILL)")
    chk(n == 100 * 50, "读到 PIXCNT = %d (期望 5000)" % n)
    chk(ok, "fill 报告成功")

    # ---------- 3. LINE ----------
    print("\n[3] line() 寄存器写入")
    m = MockRegs()
    g = GPU(verbose=False, mem=m)
    n, ok = g.line(base=0x3F100000, stride=3072, x0=0, y0=0, x1=7, y1=7,
                   color=0x00FF00)
    chk(m.last(0x04) == 1, "OP = 1 (LINE)")
    chk(m.last(0x10) == 0, "XY0 = (0,0)")
    chk(m.last(0x14) == ((7 << 16) | 7), "XY1 = (7,7)")
    chk(n == 8, "PIXCNT = %d (期望 8)" % n)
    chk(ok, "line 报告成功")

    # ---------- 4. 边界: 大坐标位打包 ----------
    print("\n[4] 坐标位打包边界 (16 位)")
    m = MockRegs()
    g = GPU(verbose=False, mem=m)
    g.fill(base=0, stride=3072, x0=1023, y0=599, w=1, h=1, color=0x000000)
    chk(m.last(0x10) == ((1023 << 16) | 599), "XY0 大坐标正确 (1023,599)")
    chk(m.last(0x14) == ((1023 << 16) | 599), "XY1 单像素 = XY0")

    # ---------- 5. 错误状态 ----------
    print("\n[5] 总线错误上报")
    m = MockRegs()
    m.err = True
    g = GPU(verbose=False, mem=m)
    n, ok = g.fill(base=0, stride=3072, x0=0, y0=0, w=4, h=4, color=0x111111)
    chk(not ok, "有错误时 fill 报告失败")
    chk(g.has_error(), "has_error() 读到 STATUS bit0")
    g.clear_error()
    chk(m.last(0x20) == 1, "clear_error() 写了 STATUS=1 (写1清)")

    # ---------- 6. 超时 ----------
    print("\n[6] 硬件不响应时的超时")
    m = MockRegs()
    m.respond = False
    g = GPU(verbose=False, mem=m)
    import time
    t0 = time.time()
    ok = g.wait(timeout=0.05)          # wait() 返回 bool
    dt = time.time() - t0
    chk(not ok, "wait() 超时返回 False")
    chk(dt < 1.0, "超时及时返回 (%.2fs)" % dt)

    # ---------- 7. probe 失败 ----------
    print("\n[7] probe 失败路径")
    class NoEcho(MockRegs):
        def __setitem__(self, k, v):
            pass          # 写不进去
        def __getitem__(self, k):
            if isinstance(k, slice):
                return bytes((k.stop or 0) - (k.start or 0))
            return 0
    m2 = NoEcho()
    g = GPU(verbose=False, mem=m2)
    chk(not g.probe(), "寄存器不回读时 probe 返回 False")

    print("\n" + "=" * 66)
    if fails:
        print(" ❌ %d 项失败:" % len(fails))
        for f in fails:
            print("     - " + f)
    else:
        print(" ✅ 全部通过! 驱动逻辑正确")
    print("=" * 66)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
