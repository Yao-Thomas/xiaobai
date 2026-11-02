#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope.py —— 自研示波器采集器 的 Python 驱动

板上: 通过 ctypes 加载 libscope.so, 寄存器在 0x43CC0000。
PC 上: 没有 /dev/mem, 自动退化成"内部仿真信号源", 方便先调 UI。

⚠️ 安全: 只有在标记文件存在时才去碰 /dev/mem。
   访问未解码的地址会触发 SIGBUS, Python 抓不住, 进程会直接被打死。
"""
import ctypes
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libscope.so")

MARKER = "/home/zynq/.scope_addr"
DEFAULT_BASE = 0x43CC0000

FCLK_HZ = 100.0e6            # PL 时钟

WAVE_SINE, WAVE_SQUARE, WAVE_TRI, WAVE_SAW = 0, 1, 2, 3
WAVE_NAMES = ("正弦", "方波", "三角", "锯齿")
MODE_AUTO, MODE_NORMAL, MODE_SINGLE = 0, 1, 2
MODE_NAMES = ("Auto", "Normal", "Single")

# 时基档位: (DIV, DEC) -> 每点时间
#   t_per_sample = DIV * DEC / 100MHz
#
# ★★★ 2026-10-03 加了 13 个【慢档】（原来的只到 12.7us/点）
# ────────────────────────────────────────────────────────────────
# 起因：查 HDL 时发现 div 是【16 位】、dec 是【8 位】，
#   而硬件只限制 div >= 4（div_ok = div < 4 ? 4 : div）——
#   ⇒ 最慢每点 = 65535 * 255 / 100MHz = 167 ms，窗口 4096 点 = 11 分钟。
#   也就是说【慢采样在 PL 层面一直就支持】，只是 Python 这里没给档位。
#
#   所以这是纯软件的收益，不用改 HDL、不用重新出流：
#     · 原来最慢 12.7us/点（窗口 52ms）—— 只能看到 19 Hz 以上
#     · 现在最慢 167ms/点（窗口 11 分钟）—— 1 Hz 以下都能看完整周期
#
#   ★ 另一个副作用（以后有用）：adc_clk = 100MHz / DIV，
#     DIV=2083 时正好是 48 kHz —— 也就是音频采样率。
#     将来若把音频接进采集器，时基表里直接有匹配的档。
#
#   ★ 分档用"1-2-5"序列，和示波器的习惯一致（好按、好读）。
TIMEBASES = [
    (5, 1,  "50ns/点"),
    (5, 2,  "100ns/点"),
    (5, 5,  "250ns/点"),
    (5, 10, "500ns/点"),
    (5, 20, "1us/点"),
    (5, 50, "2.5us/点"),
    (5, 100, "5us/点"),
    (5, 200, "10us/点"),
    (5, 250, "12.5us/点"),
    (5, 254, "12.7us/点"),
    # ---- 以下为 2026-10-03 新增的慢档 ----
    (2000, 1,   "20us/点"),
    (5000, 1,   "50us/点"),
    (10000, 1,  "100us/点"),
    (20000, 1,  "200us/点"),
    (50000, 1,  "500us/点"),
    (50000, 2,  "1ms/点"),
    (50000, 4,  "2ms/点"),
    (50000, 10, "5ms/点"),
    (50000, 20, "10ms/点"),
    (50000, 40, "20ms/点"),
    (50000, 100, "50ms/点"),
    (50000, 200, "100ms/点"),
    (65535, 255, "167ms/点"),
]


def freq_word(hz, fs_hz=20.0e6):
    """把频率换算成 DDS 频率字"""
    return int(round(hz / fs_hz * (1 << 32))) & 0xFFFFFFFF


def word_freq(word, fs_hz=20.0e6):
    return word * fs_hz / float(1 << 32)


class Scope:
    def __init__(self, base=None, verbose=True):
        self.hw = False
        self.why = ""
        self.base = DEFAULT_BASE
        self.lib = None
        self.sim_phase = 0
        self.sim_wave = WAVE_SINE
        self.sim_freq_hz = 1000.0
        self.tb_index = 4
        self.mode = MODE_AUTO

        if base is None:
            try:
                base = int(open(MARKER).read().strip(), 0)
            except Exception:
                base = None

        if base is None:
            self.why = "缺 %s (bitstream 里没有采集器?)" % MARKER
        elif not os.path.exists(LIB):
            self.why = "没有 %s" % os.path.basename(LIB)
        else:
            try:
                lib = ctypes.CDLL(LIB)
                lib.sc_open.argtypes = [ctypes.c_uint]
                lib.sc_open.restype = ctypes.c_int
                lib.sc_probe.restype = ctypes.c_int
                lib.sc_read_frame.argtypes = [ctypes.c_char_p, ctypes.c_int]
                lib.sc_read_frame.restype = ctypes.c_int
                lib.sc_version_str.restype = ctypes.c_char_p
                for fn in ("sc_set_src", "sc_set_trigcfg"):
                    getattr(lib, fn).argtypes = [ctypes.c_int, ctypes.c_int]
                for fn in ("sc_set_div", "sc_set_dec", "sc_set_freq",
                           "sc_set_triglev", "sc_set_pre"):
                    getattr(lib, fn).argtypes = [ctypes.c_uint]
                lib.sc_start.argtypes = []
                lib.sc_probe.argtypes = []
                # ★ 输出缓冲是可写的 bytearray, 不能用 c_char_p
                #   (c_char_p 只收 bytes, 传 bytearray 会 TypeError)。
                #   用 POINTER(c_ubyte) + from_buffer 共享内存。
                lib.sc_render.argtypes = [ctypes.POINTER(ctypes.c_ubyte),
                                          ctypes.c_int, ctypes.c_int,
                                          ctypes.c_char_p, ctypes.c_int,
                                          ctypes.c_uint]
                lib.sc_render.restype = None
                lib.sc_measure.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_int)]
                lib.sc_measure.restype = None
                lib.sc_read_frame.argtypes = [ctypes.c_char_p, ctypes.c_int]
                r = lib.sc_open(ctypes.c_uint(base))
                if r != 0:
                    self.why = "sc_open 失败 (%d)" % r
                elif not lib.sc_probe():
                    self.why = ("0x%08X 无响应 (VERSION 不对, bitstream 没加载?)"
                                % base)
                else:
                    self.lib = lib
                    self.base = base
                    self.hw = True
            except Exception as ex:
                self.why = "加载失败: %s" % ex

        if verbose:
            if self.hw:
                print("示波器采集器已启用: %s"
                      % self.lib.sc_version_str().decode())
            else:
                print("采集器不可用, 用内部仿真波形: %s" % self.why)

    # ---------------- 配置 ----------------
    def timebase(self):
        return TIMEBASES[self.tb_index]

    def t_per_sample(self):
        div, dec, _ = self.timebase()
        return div * dec / FCLK_HZ

    def set_timebase(self, idx):
        self.tb_index = max(0, min(len(TIMEBASES) - 1, idx))
        if self.hw:
            div, dec, _ = self.timebase()
            self.lib.sc_set_div(ctypes.c_uint(div))
            self.lib.sc_set_dec(ctypes.c_uint(dec))

    def configure(self, src=None, wave=None, timebase=None, triglev=None,
                  edge=None, mode=None, pre=None, dds_hz=None):
        if wave is not None:
            self.sim_wave = wave
        if dds_hz is not None:
            self.sim_freq_hz = dds_hz
        if timebase is not None:
            self.set_timebase(timebase)
        if mode is not None:
            self.mode = mode
        if src is not None:
            self.src = src
        if not self.hw:
            return
        L = self.lib
        if src is not None and wave is not None:
            L.sc_set_src(ctypes.c_int(src), ctypes.c_int(wave))
        if dds_hz is not None:
            L.sc_set_freq(ctypes.c_uint(freq_word(dds_hz)))
        if triglev is not None:
            L.sc_set_triglev(ctypes.c_uint(int(triglev) & 0xFF))
        if edge is not None and mode is not None:
            L.sc_set_trigcfg(ctypes.c_int(edge), ctypes.c_int(mode))
        if pre is not None:
            L.sc_set_pre(ctypes.c_uint(int(pre) & 0xFFF))

    # ---------------- 采集 ----------------
    def capture(self, timeout_us=4000000):
        if not self.hw:
            return True
        self.lib.sc_start()
        return bool(self.lib.sc_wait(ctypes.c_int(timeout_us)))

    def read_frame(self, n=4096):
        """返回 bytearray, 按时间顺序 (最老 -> 最新)"""
        if not self.hw:
            return self._sim_frame(n)
        buf = ctypes.create_string_buffer(n)
        got = self.lib.sc_read_frame(buf, ctypes.c_int(n))
        if got <= 0:
            return bytearray(n)
        return bytearray(buf.raw[:got])

    def _sim_frame(self, n):
        """PC 上用的仿真波形 (和 PL 里的 DDS 一个意思)"""
        div, dec, _ = self.timebase()
        ts = div * dec / FCLK_HZ
        per = 1.0 / self.sim_freq_hz
        out = bytearray(n)
        for i in range(n):
            ph = ((i * ts) / per) % 1.0
            if self.sim_wave == WAVE_SINE:
                v = 127.5 + 127.5 * math.sin(2 * math.pi * ph)
            elif self.sim_wave == WAVE_SQUARE:
                v = 255 if ph < 0.5 else 0
            elif self.sim_wave == WAVE_TRI:
                v = 255 * (2 * ph if ph < 0.5 else 2 * (1 - ph))
            else:
                v = 255 * ph
            out[i] = max(0, min(255, int(v)))
        return out

    def status(self):
        if not self.hw:
            return {}
        L = self.lib
        return {
            "done": bool(L.sc_done()),
            "busy": bool(L.sc_busy()),
            "triggered": bool(L.sc_triggered()),
            "bank": int(L.sc_bank()),
            "start": int(L.sc_start_addr()),
            "wr": int(L.sc_wr_total()),
            "err": bool(L.sc_status() & 1),
        }

    # ---------------- 测量 ----------------
    def measure(self, data):
        """从采样数据算 频率 / Vpp / 峰谷 / 占空比

        板上走 C (sc_measure): Python 循环 4096 次要 9ms, C 里 ~0.1ms。
        """
        n = len(data)
        if n < 8:
            return {}
        ts = self.t_per_sample()

        if self.hw and self.lib is not None:
            buf = ctypes.create_string_buffer(bytes(data), n)
            out = (ctypes.c_int * 7)()
            self.lib.sc_measure(buf, ctypes.c_int(n), out)
            mn, mx, mid = out[0], out[1], out[2]
            ne = out[3]
            span = out[4]
            hi = out[5]
            per = (span / float(ne - 1)) if (ne >= 2 and span > 0) else None
        else:
            mn = min(data)
            mx = max(data)
            mid = (mn + mx) // 2
            idx = [i for i in range(1, n) if data[i - 1] < mid <= data[i]]
            ne = len(idx)
            per = ((idx[-1] - idx[0]) / float(ne - 1)) if ne >= 2 else None
            hi = sum(1 for v in data if v > mid)

        freq = (1.0 / (per * ts)) if (per and per > 0) else None
        duty = hi * 100.0 / n

        return {
            "min": mn, "max": mx, "mid": mid, "pp": mx - mn,
            "period": per, "freq": freq, "duty": duty,
            "edges": ne, "t_per_sample": ts,
        }

    # ---------------- 渲染 ----------------
    def render(self, buf, w, h, data=None, color=0x5AFFAA):
        """把采样渲染成 w*h*3 的 BGR 缓冲 (每列 min/max 竖线)

        板上走 C (sc_render)。返回 True 表示渲染成功。
        """
        d = self.data if data is None else data
        n = len(d)
        if n < 4 or w <= 0 or h <= 0:
            return False
        if self.hw and self.lib is not None:
            arr = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            self.lib.sc_render(arr, ctypes.c_int(w), ctypes.c_int(h),
                               bytes(d), ctypes.c_int(n),
                               ctypes.c_uint(color))
            return True
        # PC 上的纯 Python 兜底 (慢, 只为能看)
        cb, cg, cr = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        for px in range(w):
            a = px * n // w
            e = max(a + 1, (px + 1) * n // w)
            e = min(e + 1, n)          # 含边界样本, 相邻列才接得上
            seg = d[a:e]
            if not seg:
                break
            lo, hi = min(seg), max(seg)
            y0 = (h - 1) - hi * (h - 1) // 255
            y1 = (h - 1) - lo * (h - 1) // 255
            if y1 <= y0:
                y1 = y0 + 1
            for y in range(max(0, y0), min(h - 1, y1) + 1):
                o = (y * w + px) * 3
                buf[o] = cb
                buf[o + 1] = cg
                buf[o + 2] = cr
        return True

    def close(self):
        if self.lib:
            self.lib.sc_close()
            self.lib = None
            self.hw = False


def probe():
    """只探测, 给别的地方用"""
    s = Scope(verbose=False)
    ok = s.hw
    why = s.why
    s.close()
    return ok, why
