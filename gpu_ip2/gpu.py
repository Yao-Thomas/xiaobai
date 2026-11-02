#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gpu.py —— Zynq FPGA GPU (gpu2d_axi) 的 Linux 驱动
  通过 /dev/mem 映射 AXI4-Lite 寄存器, 驱动 PL 里的 2D 加速器

寄存器 (偏移):
  0x00 CTRL    W[0]=start     R[0]=done R[1]=busy
  0x04 OP      0=FILL 1=LINE
  0x08 BASE    显存基址
  0x0C STRIDE  行跨距(字节)
  0x10 XY0     [31:16]=x0 [15:0]=y0
  0x14 XY1     [31:16]=x1 [15:0]=y1
  0x18 COLOR   0xRRGGBB
  0x1C PIXCNT  已写像素数
"""
import mmap, os, struct, time

PAGE = 4096


class GPU:
    def __init__(self, base=0x43CB0000, verbose=True, mem=None):
        """mem 参数用于单元测试: 传入一个可读写切片的对象(如 bytearray)即可,
           此时不碰 /dev/mem。"""
        self.base = base
        self.verbose = verbose
        if base % PAGE:
            raise ValueError("基址必须页对齐")
        if mem is not None:
            self.fd = -1
            self.mm = mem
            self._mock = True
        else:
            self._mock = False
            self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
            self.mm = mmap.mmap(self.fd, PAGE, mmap.MAP_SHARED,
                                mmap.PROT_READ | mmap.PROT_WRITE, offset=base)

    # ---- 寄存器读写 ----
    def wr(self, off, val):
        self.mm[off:off + 4] = struct.pack("<I", val & 0xFFFFFFFF)

    def rd(self, off):
        return struct.unpack("<I", self.mm[off:off + 4])[0]

    def probe(self):
        """探测 GPU 是否存在: 写 COLOR 再读回"""
        self.wr(0x18, 0x5A5A5A)
        v = self.rd(0x18)
        ok = (v == 0x5A5A5A)
        if self.verbose:
            print("GPU 探测 @0x%08X: COLOR 回读 = 0x%06X -> %s" %
                  (self.base, v, "存在 ✅" if ok else "不存在 ❌"))
        return ok

    # ---- 操作 ----
    def _setup(self, op, base, stride, x0, y0, x1, y1, color):
        self.wr(0x08, base)
        self.wr(0x0C, stride)
        self.wr(0x10, ((x0 & 0xFFFF) << 16) | (y0 & 0xFFFF))
        self.wr(0x14, ((x1 & 0xFFFF) << 16) | (y1 & 0xFFFF))
        self.wr(0x18, color & 0xFFFFFF)
        self.wr(0x04, op)

    def start(self):
        self.wr(0x00, 1)

    def wait(self, expected=None, timeout=5.0):
        """等操作完成

        ★★★ 这里以前有个致命 bug ★★★

        核心 (gpu2d.v) 的 FSM 是:
            S_DONE: done <= 1'b1;  state <= S_IDLE;
            S_IDLE: done <= 1'b0;            // 下一拍就清掉
        所以 CTRL 的 done 位【只持续 1 个时钟周期】(100MHz 下 = 10ns)。
        软件轮询一次要 ~1µs, 根本不可能抓到它 ——
        结果每次操作都白等 5 秒然后误判成"失败",
        而硬件其实每次都干完了 (PIXCNT 都数到整屏 614400 了)。

        现在改成【看 PIXCNT】: 数到预期的像素数就是完成了, 这个计数是
        锁存住的, 绝对不会漏。同时也保留抓 done 脉冲这条退路。
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.has_error():
                return False
            if expected is not None and self.rd(0x1C) >= expected:
                return True
            if self.rd(0x00) & 0x1:          # done 脉冲, 偶尔也能抓到
                return True
            time.sleep(0.0002)
        return False

    def fill(self, base, stride, x0, y0, w, h, color):
        """矩形填充: 用左上角+宽高"""
        self.clear_error()
        self._setup(0, base, stride, x0, y0, x0 + w - 1, y0 + h - 1, color)
        self.start()
        ok = self.wait(expected=w * h)
        n = self.rd(0x1C)
        if self.verbose:
            print("  填充 (%d,%d) %dx%d 颜色#%06X -> %d 像素 (期望 %d) %s" %
                  (x0, y0, w, h, color, n, w * h, "✅" if ok else "失败❌"))
        return n, ok

    def line(self, base, stride, x0, y0, x1, y1, color):
        self.clear_error()
        self._setup(1, base, stride, x0, y0, x1, y1, color)
        # Bresenham 的像素数 = max(|dx|,|dy|) + 1
        expect = max(abs(x1 - x0), abs(y1 - y0)) + 1
        self.start()
        ok = self.wait(expected=expect)
        n = self.rd(0x1C)
        if self.verbose:
            print("  直线 (%d,%d)->(%d,%d) -> %d 像素 (期望 %d) %s" %
                  (x0, y0, x1, y1, n, expect, "✅" if ok else "失败❌"))
        return n, ok

    def version(self):
        return self.rd(0x20)

    # ---- 错误状态 (总线超时保护) ----
    def status(self):
        """读 STATUS: bit0 = 出错(总线超时/核心报错)"""
        return self.rd(0x20)

    def has_error(self):
        return (self.rd(0x20) & 1) == 1

    def clear_error(self):
        """写 1 清错误标志"""
        self.wr(0x20, 1)

    @property
    def last_error(self):
        return self._err

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass
        if self.fd >= 0:
            os.close(self.fd)


def find_gpu(candidates=(0x43CB0000, 0x43CC0000, 0x43CD0000, 0x43CE0000)):
    """在候选地址里找 GPU

    ⚠️ 只能用【空闲地址】! 探测会写寄存器(0x18=0x5A5A5A),
       误写其他外设(GPIO/PWM/VTC)会造成危险。
       正点原子设计已占用 0x43C00000~0x43CAFFFF, 所以从 0x43CB0000 起找。
    """
    for a in candidates:
        try:
            g = GPU(a, verbose=False)
            if g.probe():
                g.verbose = True
                print("找到 GPU: 0x%08X" % a)
                return g
            g.close()
        except Exception as ex:
            print("  探测 0x%08X 失败: %s" % (a, ex))
    return None


if __name__ == "__main__":
    g = find_gpu()
    if g:
        print("寄存器快照:")
        for name, off in (("CTRL", 0), ("OP", 4), ("BASE", 8), ("STRIDE", 0xC),
                          ("XY0", 0x10), ("XY1", 0x14), ("COLOR", 0x18), ("PIXCNT", 0x1C)):
            print("  %-8s = 0x%08X" % (name, g.rd(off)))
        g.close()
    else:
        print("没找到 GPU (bitstream 还没加载?)")
