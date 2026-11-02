#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gpufill.py —— 把矩形/直线【批量】交给 FPGA 上的自研 GPU 画

板上: ctypes 加载 libgpubatch.so。一次 commit() 就是一次 gb_batch(),
      所有寄存器操作都在 C 里紧凑做完 —— 每个矩形只摊到几微秒。
      (Python 驱动每个操作要 6 次寄存器写 + 一次带 sleep 的 wait(),
       至少 0.2ms。几百个方块就 40ms+, GPU 再快也白搭。)
PC 上: 没有 /dev/mem, 自动退化成 PIL 画进 scr.img, 方便本地调游戏逻辑。

用法:
    gf = GpuFill(scr)
    gf.begin()
    gf.rect(10, 10, 100, 50, 0xFF0000)
    gf.line(0, 0, 1023, 599, 0x00FF00)
    gf.commit()
    print(gf.hw, gf.n_ops, gf.px, gf.ms)

★ 屏幕上"GPU 拥有的像素"和"PIL 拥有的像素"必须分区, 不能重叠:
  硬件是直接写显存的, PIL 那边走 blit_raw 推小块, 谁画谁负责。
"""
import array
import ctypes
import os

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libgpubatch.so")

OP_FILL = 0
OP_LINE = 1

# 复用的 ctypes 缓冲, 免得每帧重新分配
_BUF_CAP = 0
_BUF = None


def _try_load():
    """哪一步失败就返回 (None, 原因)"""
    if not os.path.exists(LIB):
        return None, "没有 %s" % os.path.basename(LIB)
    try:
        lib = ctypes.CDLL(LIB)
    except Exception as ex:
        return None, "加载失败: %s" % ex
    p = ctypes.POINTER(ctypes.c_int)
    lib.gb_open.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
    lib.gb_open.restype = ctypes.c_int
    lib.gb_probe.restype = ctypes.c_int
    lib.gb_ready.restype = ctypes.c_int
    lib.gb_batch.argtypes = [p, ctypes.c_int]
    lib.gb_batch.restype = ctypes.c_int
    lib.gb_fill.argtypes = [ctypes.c_int] * 4 + [ctypes.c_uint]
    lib.gb_line.argtypes = [ctypes.c_int] * 4 + [ctypes.c_uint]
    lib.gb_stats_reset.argtypes = []
    lib.gb_stats.argtypes = [ctypes.POINTER(ctypes.c_long)] * 2 + \
                            [ctypes.POINTER(ctypes.c_double)] * 2
    lib.gb_set_fb.argtypes = [ctypes.c_uint, ctypes.c_int]
    lib.gb_get_base.restype = ctypes.c_uint
    lib.gb_post.argtypes = [ctypes.c_int] * 5 + [ctypes.c_uint]
    lib.gb_post.restype = ctypes.c_long
    lib.gb_sync.argtypes = []
    lib.gb_idle.restype = ctypes.c_int
    lib.gb_post_batch.argtypes = [p, ctypes.c_int]
    lib.gb_post_batch.restype = ctypes.c_int
    lib.cb_rects.argtypes = [p, ctypes.c_int]
    lib.cb_rects.restype = ctypes.c_int
    lib.cb_stats.argtypes = [ctypes.POINTER(ctypes.c_long)]
    lib.cb_stats.restype = ctypes.c_double
    lib.cb_stats_reset.argtypes = []
    lib.gb_version.restype = ctypes.c_char_p
    return lib, None


class GpuFill:
    def __init__(self, scr, base=0x43CB0000, verbose=True):
        self.scr = scr
        self.hw = False
        self.why = ""
        self.base = base
        self.lib = None
        self._ops = []
        self.n_ops = 0
        self.px = 0
        self.ms = 0.0
        self.ms_max = 0.0
        self.total_px = 0
        self.total_ops = 0
        self.frames = 0
        if not getattr(scr, "phys", 0):
            self.why = "拿不到显存物理地址"
        else:
            lib, why = _try_load()
            if lib is None:
                self.why = why
            else:
                r = lib.gb_open(base, scr.phys, scr.stride)
                if r != 0:
                    self.why = "gb_open 失败 (%d)" % r
                elif not lib.gb_probe():
                    self.why = "探测 0x%08X 无响应 (bitstream 没加载?)" % base
                else:
                    self.lib = lib
                    self.hw = True
        if verbose:
            if self.hw:
                print("GPU 批量填充已启用: %s @0x%08X"
                      % (self.lib.gb_version().decode(), base))
            else:
                print("GPU 不可用, 退化成软件绘制: %s" % self.why)
                print("  (PC 上跑是这样; 板子上要确认 bitstream 和 .gpu_addr)")

    # ---------- 一帧 ----------
    def begin(self):
        # ★ 用 array('i') 累积: extend 是 C 层批量转换,
        #   比 (c_int*n)(*list) 那种逐个转换快得多(实测省一半以上开销)
        self._ops = array.array("i")
        self.n_ops = 0
        self.px = 0
        self.ms = 0.0
        if self.hw:
            self.lib.gb_stats_reset()

    def rect(self, x0, y0, x1, y1, color):
        """闭区间矩形。硬件会把 x/y 夹到非负, 但别依赖它"""
        if x1 < x0 or y1 < y0:
            return
        self.n_ops += 1
        self.px += (x1 - x0 + 1) * (y1 - y0 + 1)
        if self.hw:
            self._ops.extend((OP_FILL, x0, y0, x1, y1, color & 0xFFFFFF))
        else:
            self.scr.d.rectangle([x0, y0, x1, y1],
                                 fill=((color >> 16) & 255, (color >> 8) & 255,
                                       color & 255))

    def line(self, x0, y0, x1, y1, color):
        self.n_ops += 1
        self.px += max(abs(x1 - x0), abs(y1 - y0)) + 1
        if self.hw:
            self._ops.extend((OP_LINE, x0, y0, x1, y1, color & 0xFFFFFF))
        else:
            self.scr.d.line([(x0, y0), (x1, y1)],
                            fill=((color >> 16) & 255, (color >> 8) & 255,
                                  color & 255))

    def frame(self, x, y, w, h, border, fill):
        """带 1 像素边框的实心矩形 (两个 op)"""
        self.rect(x, y, x + w - 1, y + h - 1, border)
        if w > 2 and h > 2:
            self.rect(x + 1, y + 1, x + w - 2, y + h - 2, fill)

    def commit(self):
        if not self.hw:
            self.total_ops += self.n_ops
            self.total_px += self.px
            self.frames += 1
            return self.n_ops
        n = len(self._ops) // 6
        if n == 0:
            return 0
        global _BUF, _BUF_CAP
        need = len(self._ops)
        if need > _BUF_CAP:
            _BUF_CAP = need * 2 + 600
            _BUF = (ctypes.c_int * _BUF_CAP)()
        ctypes.memmove(_BUF, self._ops.buffer_info()[0], need * 4)
        self.lib.gb_batch(_BUF, n)
        o = ctypes.c_long(0)
        p = ctypes.c_long(0)
        ms = ctypes.c_double(0.0)
        mm = ctypes.c_double(0.0)
        self.lib.gb_stats(ctypes.byref(o), ctypes.byref(p),
                          ctypes.byref(ms), ctypes.byref(mm))
        self.n_ops = o.value
        self.px = p.value
        self.ms = ms.value
        self.ms_max = mm.value
        self.total_ops += o.value
        self.total_px += p.value
        self.frames += 1
        self._ops = array.array("i")
        return self.n_ops

    # ---------- 异步接口 (让 GPU 绘图和 CPU 计算重叠) ----------
    def post(self, x0, y0, x1, y1, color):
        """提交一个矩形但不等待 —— 之后 CPU 可以立刻去干别的"""
        if not self.hw:
            self.rect(x0, y0, x1, y1, color)
            return 0
        self.n_ops += 1
        self.px += (x1 - x0 + 1) * (y1 - y0 + 1)
        return self.lib.gb_post(0, int(x0), int(y0), int(x1), int(y1),
                                int(color) & 0xFFFFFF)

    def post_line(self, x0, y0, x1, y1, color):
        if not self.hw:
            self.line(x0, y0, x1, y1, color)
            return 0
        self.n_ops += 1
        return self.lib.gb_post(1, int(x0), int(y0), int(x1), int(y1),
                                int(color) & 0xFFFFFF)

    def sync(self):
        """等 GPU 把提交的活干完"""
        if self.hw:
            self.lib.gb_sync()

    def idle(self):
        if not self.hw:
            return True
        return bool(self.lib.gb_idle())

    def commit_cpu(self):
        """把这一批矩形交给【C 写的 CPU 填充器】画。

        ★ 只用于公平对比。不加这个, "GPU vs CPU"就是假的 ——
          GPU 那边走 C 批量驱动, CPU 那边如果用 Python 的 fill_raw,
          会慢一个数量级, GPU 白捡好几倍。两边必须是同一份矩形表、
          同一种调用方式, 区别只在"交给硬件"还是"CPU 自己写内存"。
        """
        n = len(self._ops) // 6
        if n == 0:
            return 0
        arr = (ctypes.c_int * len(self._ops)).from_buffer_copy(self._ops)
        r = self.lib.cb_rects(arr, n)
        self.total_ops += n
        self.total_px += self.px
        self.frames += 1
        self._ops = array.array("i")
        return r

    def cpu_stats(self):
        if not self.lib:
            return 0.0, 0
        p = ctypes.c_long(0)
        ms = self.lib.cb_stats(ctypes.byref(p))
        return ms, p.value

    # ---------- 统计 ----------
    def reset_totals(self):
        self.total_ops = 0
        self.total_px = 0
        self.frames = 0

    def cover_pct(self, screen_px=1024 * 600):
        return self.px * 100.0 / screen_px

    def close(self):
        if self.lib:
            self.lib.gb_close()
            self.lib = None
            self.hw = False


def probe():
    """给别的程序用: 只探测 GPU 在不在"""
    lib, why = _try_load()
    if lib is None:
        return False, why
    if lib.gb_open(0x43CB0000, 0, 0) != 0:
        return False, "gb_open 失败"
    ok = bool(lib.gb_probe())
    lib.gb_close()
    return ok, ("OK" if ok else "无响应")
