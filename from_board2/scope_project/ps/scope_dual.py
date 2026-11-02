#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_dual.py —— 双通道示波器（3PA1030 ×2）的 Python 驱动

板上: ctypes 加载 libscopedual.so，寄存器在 0x43CC0000（和老的单通道示波器
      同一个地址，所以 /home/zynq/.scope_addr 标记文件可以复用）。
PC 上: 没有 /dev/mem 时退化成内部仿真波形，方便先调界面。

和老 scope.py 的区别：
  · 老 IP 的 VERSION 魔数是 0x53434F50 ("SCOP")，新的是 0x53435032 ("SCP2")
    —— 所以必须用新的 libscopedual.so，老库 probe 一定失败
  · 采样 10 位（0..1023）而不是 8 位
  · 一次采集同时拿到 CH1/CH2 两路
  · 触发电平 10 位、预触发 12 位、抽取 16 位
  · 多了 CAPS / RATE / FRAMESEQ

⚠️ 安全: 只有在标记文件存在时才去碰 /dev/mem。
   访问未解码的地址会触发 SIGBUS，Python 抓不住，进程会直接被杀死。
"""
import ctypes
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libscopedual.so")

MARKER = "/home/zynq/.scope_addr"
DEFAULT_BASE = 0x43CC0000

FCLK_HZ = 100.0e6            # PL 递给 ADC 时钟模块的时钟
ADC_FS_HZ = 20.0e6           # ADC 实际采样率（clk_wiz 20MHz）
DEPTH = 4096
SAMPLE_MAX = 1023            # 10 位

MODE_AUTO, MODE_NORMAL, MODE_SINGLE = 0, 1, 2
MODE_NAMES = ("Auto", "Normal", "Single")

# 时基档位: (DIV, DEC) -> 每点时间。DIV 由 IP 固定回读为 5
TIMEBASES = [
    (5, 1,   "50ns/点"),
    (5, 2,   "100ns/点"),
    (5, 5,   "250ns/点"),
    (5, 10,  "500ns/点"),
    (5, 20,  "1us/点"),
    (5, 50,  "2.5us/点"),
    (5, 100, "5us/点"),
    (5, 200, "10us/点"),
    (5, 250, "12.5us/点"),
    (5, 254, "12.7us/点"),
]


def mv_per_lsb():
    """输入 ±5V 经 VO = VI/5 + 1 衰减到 0~2V 给 ADC。
    10 位 ADC 满量程 2V -> 1023，所以 1 LSB ≈ 1.955 mV（指 ADC 输入端）。
    换算回【模块输入端】要 ×5，即 ≈ 9.77 mV/LSB。"""
    return 10000.0 / 1023.0


class ScopeDual:
    def __init__(self, base=None, verbose=True):
        self.hw = False
        self.why = ""
        self.base = DEFAULT_BASE
        self.lib = None
        self.tb_index = 4
        self.mode = MODE_AUTO
        self.trig_channel = 0
        self.trig_level = 512
        self.trig_edge = 0

        # 仿真用
        self.sim_freq_hz = 1000.0
        self.sim_freq2_hz = 3000.0

        if base is None:
            try:
                base = int(open(MARKER).read().strip(), 0)
            except Exception:
                base = None

        if base is None:
            self.why = "缺 %s（bitstream 里没有双通道采集器？）" % MARKER
        elif not os.path.exists(LIB):
            self.why = "没有 %s" % os.path.basename(LIB)
        else:
            try:
                lib = ctypes.CDLL(LIB)
                lib.sd_open.argtypes = [ctypes.c_uint]
                lib.sd_open.restype = ctypes.c_int
                lib.sd_probe.restype = ctypes.c_int
                lib.sd_version.restype = ctypes.c_uint
                lib.sd_caps.restype = ctypes.c_uint
                lib.sd_rate.restype = ctypes.c_uint
                lib.sd_frameseq.restype = ctypes.c_uint
                lib.sd_start_addr.restype = ctypes.c_uint
                lib.sd_wr_total.restype = ctypes.c_uint
                lib.sd_version_str.restype = ctypes.c_char_p
                for fn in ("sd_set_div", "sd_set_dec", "sd_set_triglev",
                           "sd_set_pre", "sd_set_src"):
                    getattr(lib, fn).argtypes = [ctypes.c_uint]
                lib.sd_set_trigcfg.argtypes = [ctypes.c_int] * 3
                lib.sd_wait.argtypes = [ctypes.c_int]
                lib.sd_wait.restype = ctypes.c_int
                lib.sd_capture.restype = ctypes.c_int
                lib.sd_read_raw.argtypes = [ctypes.POINTER(ctypes.c_uint),
                                            ctypes.c_int]
                lib.sd_read_raw.restype = ctypes.c_int
                lib.sd_read_ch.argtypes = [ctypes.POINTER(ctypes.c_ushort),
                                           ctypes.POINTER(ctypes.c_ushort),
                                           ctypes.c_int]
                lib.sd_read_ch.restype = ctypes.c_int
                # ★ 输出缓冲是 bytearray，必须用 POINTER(c_ubyte)+from_buffer
                lib.sd_render.argtypes = [ctypes.POINTER(ctypes.c_ubyte),
                                          ctypes.c_int, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_ushort),
                                          ctypes.c_int, ctypes.c_uint,
                                          ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int]
                lib.sd_render.restype = None
                lib.sd_measure.argtypes = [ctypes.POINTER(ctypes.c_ushort),
                                           ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_int)]
                lib.sd_measure.restype = None
                lib.sd_measure_ex.argtypes = [ctypes.POINTER(ctypes.c_ushort),
                                              ctypes.c_int, ctypes.c_int,
                                              ctypes.POINTER(ctypes.c_double)]
                lib.sd_measure_ex.restype = None
                lib.sd_envelope.argtypes = [ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.c_int, ctypes.c_int]
                lib.sd_envelope.restype = None
                lib.sd_draw_env.argtypes = [ctypes.POINTER(ctypes.c_ubyte),
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.POINTER(ctypes.c_ushort),
                                            ctypes.c_int, ctypes.c_uint,
                                            ctypes.c_double, ctypes.c_double]
                lib.sd_draw_env.restype = None
                lib.sd_draw_trace.argtypes = [ctypes.POINTER(ctypes.c_ubyte),
                                              ctypes.c_int, ctypes.c_int,
                                              ctypes.POINTER(ctypes.c_ushort),
                                              ctypes.c_int, ctypes.c_uint,
                                              ctypes.c_double, ctypes.c_double]
                lib.sd_draw_trace.restype = None
                lib.sd_read_frame_locked.argtypes = [
                    ctypes.POINTER(ctypes.c_ushort),
                    ctypes.POINTER(ctypes.c_ushort), ctypes.c_int,
                    ctypes.POINTER(ctypes.c_uint)]
                lib.sd_read_frame_locked.restype = ctypes.c_int
                for fn in ("sd_stats1", "sd_stats2", "sd_edge1", "sd_edge2"):
                    getattr(lib, fn).restype = ctypes.c_uint

                r = lib.sd_open(ctypes.c_uint(base))
                if r != 0:
                    self.why = "sd_open 失败 (%d)" % r
                elif not lib.sd_probe():
                    got = 0
                    try:
                        got = lib.sd_version()
                    except Exception:
                        pass
                    self.why = ("0x%08X 读到的 VERSION=0x%08X，不是 SCP2"
                                "（bitstream 没加载？还是老的单通道版？）"
                                % (base, got))
                else:
                    self.lib = lib
                    self.base = base
                    self.hw = True
            except Exception as ex:
                self.why = "加载失败: %s" % ex

        if verbose:
            if self.hw:
                print("双通道采集器已启用: %s"
                      % self.lib.sd_version_str().decode())
                caps = self.lib.sd_caps()
                print("  CAPS=0x%08X  通道=%d  位宽=%d  深度=%d  采样率=%.2f MHz"
                      % (caps, (caps >> 28) & 0xF, (caps >> 20) & 0xFF,
                         caps & 0xFFFF, self.lib.sd_rate() / 1e6))
            else:
                print("采集器不可用，用内部仿真波形: %s" % self.why)

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
            self.lib.sd_set_div(ctypes.c_uint(div))
            self.lib.sd_set_dec(ctypes.c_uint(dec))

    def set_trigcfg(self, edge=0, mode=0, source=0):
        """edge:0=上升1=下降  mode:0Auto/1Normal/2Single  source:0CH1/1CH2/2同时/3自由"""
        if not self.hw:
            return
        try:
            self.lib.sd_set_trigcfg2(ctypes.c_int(int(edge)),
                                     ctypes.c_int(int(mode)),
                                     ctypes.c_int(int(source)))
        except Exception:
            pass

    def configure(self, timebase=None, triglev=None, edge=None, mode=None,
                  pre=None, trigger_channel=None):
        if timebase is not None:
            self.set_timebase(timebase)
        if mode is not None:
            self.mode = mode
        if triglev is not None:
            self.trig_level = int(triglev)
        if edge is not None:
            self.trig_edge = int(edge)
        if trigger_channel is not None:
            self.trig_channel = int(trigger_channel)
        if not self.hw:
            return
        L = self.lib
        if triglev is not None:
            L.sd_set_triglev(ctypes.c_uint(self.trig_level & 0x3FF))
        if edge is not None or mode is not None or trigger_channel is not None:
            L.sd_set_trigcfg(ctypes.c_int(self.trig_edge),
                             ctypes.c_int(self.mode),
                             ctypes.c_int(self.trig_channel))
        if pre is not None:
            L.sd_set_pre(ctypes.c_uint(int(pre) & 0xFFF))

    # ---------------- 采集 ----------------
    def capture(self, timeout_us=4000000):
        if not self.hw:
            return True
        self.lib.sd_start()
        return bool(self.lib.sd_wait(ctypes.c_int(timeout_us)))

    def read_frame(self, n=DEPTH):
        """返回 (ch1, ch2)，都是 list[int]（10 位），按时间顺序最老->最新"""
        if not self.hw:
            return self._sim_frame(n)
        a1 = (ctypes.c_ushort * n)()
        a2 = (ctypes.c_ushort * n)()
        got = self.lib.sd_read_ch(a1, a2, ctypes.c_int(n))
        if got <= 0:
            return [0] * n, [0] * n
        return list(a1[:got]), list(a2[:got])

    def _sim_frame(self, n):
        """PC 上用的仿真：CH1 是 1kHz 正弦，CH2 是 3kHz 三角"""
        ts = self.t_per_sample()
        out1 = [0] * n
        out2 = [0] * n
        for i in range(n):
            t = i * ts
            p1 = (t * self.sim_freq_hz) % 1.0
            p2 = (t * self.sim_freq2_hz) % 1.0
            v1 = 0.5 + 0.45 * math.sin(2 * math.pi * p1)
            v2 = 0.2 + 0.6 * (2 * p2 if p2 < 0.5 else 2 * (1 - p2))
            out1[i] = max(0, min(SAMPLE_MAX, int(v1 * SAMPLE_MAX)))
            out2[i] = max(0, min(SAMPLE_MAX, int(v2 * SAMPLE_MAX)))
        return out1, out2

    def status(self):
        if not self.hw:
            return {}
        L = self.lib
        return {
            "done": bool(L.sd_done()),
            "busy": bool(L.sd_busy()),
            "triggered": bool(L.sd_triggered()),
            "bank": int(L.sd_bank()),
            "start": int(L.sd_start_addr()),
            "wr": int(L.sd_wr_total()),
            "frameseq": int(L.sd_frameseq()),
        }

    # ---------------- 测量 ----------------
    def measure(self, data):
        """算 min/max/Vpp/频率/占空比。板上走 C。"""
        n = len(data)
        if n < 8:
            return {}
        ts = self.t_per_sample()

        if self.hw and self.lib is not None:
            arr = (ctypes.c_ushort * n)(*data)
            out = (ctypes.c_int * 7)()
            self.lib.sd_measure(arr, ctypes.c_int(n), out)
            mn, mx, mid = out[0], out[1], out[2]
            ne, span, hi = out[3], out[4], out[5]
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
        k = mv_per_lsb()

        return {
            "min": mn, "max": mx, "mid": mid, "pp": mx - mn,
            "period": per, "freq": freq, "duty": duty, "edges": ne,
            "t_per_sample": ts,
            # 换算到模块输入端（×5）
            "vpp_mv": (mx - mn) * k,
            "min_mv": (mn - 512) * k,
            "max_mv": (mx - 512) * k,
        }

    # ---------------- 步骤2：迟滞 + 采集模式 ----------------
    def set_dec(self, dec):
        """直接下发抽取倍率（统一时基表算出来的 D）。
        硬件把抽取实现为 div(每点时钟数) x dec(再抽)，这里统一按 dec 下发。"""
        self.dec = max(1, min(65535, int(dec)))
        if self.hw:
            try:
                self.lib.sd_set_dec(ctypes.c_uint(self.dec))
            except Exception:
                pass

    def set_hys(self, lsb):
        """设置迟滞宽度（LSB）。hys = max(噪声x3, Vpp/32, 2)"""
        self.hys = max(2, min(1023, int(lsb)))
        if self.hw:
            try:
                self.lib.sd_set_hys(ctypes.c_uint(self.hys))
            except Exception:
                pass

    def set_acqmode(self, mode):
        """0=Auto 1=Normal 2=Single 3=Roll。Roll 是采集模式，不是触发源。"""
        self.acqmode = int(mode) & 3
        self._roll_started = False          # 切模式后允许重新 start
        if self.hw:
            try:
                self.lib.sd_set_acqmode(ctypes.c_uint(self.acqmode))
            except Exception:
                pass

    def roll_start(self):
        """Roll 模式下让核开始连续采集（write_ptr 环形前进）。"""
        if self.hw:
            try:
                self.lib.sd_start()
            except Exception:
                pass

    # ---------------- 原子读帧（步骤1）----------------
    def read_frame_locked(self, n=DEPTH):
        """锁 bank -> 读整帧 -> ACK。

        返回 (ch1, ch2, info)；info 是 dict：
            seq / bank / start / count / trig_index / lost / dec / triggered / stale
        核在 ACK 前绝不覆盖该 bank，所以这里拿到的永远是一个不可变帧，
        不会出现由两个 bank 拼成的帧。
        """
        if not self.hw:
            a = self._sim_frame(n)
            b = self._sim_frame(n)
            return a, b, {"seq": 0, "bank": 0, "start": 0, "count": n,
                          "trig_index": 0, "lost": 0, "dec": 1,
                          "triggered": True, "stale": False}
        a1 = (ctypes.c_ushort * n)()
        a2 = (ctypes.c_ushort * n)()
        info = (ctypes.c_uint * 8)()
        got = self.lib.sd_read_frame_locked(a1, a2, ctypes.c_int(n), info)
        if got <= 0:
            return None, None, {"error": got}
        d = {
            "seq": info[0], "bank": info[1], "start": info[2], "count": info[3],
            "trig_index": info[4], "lost": info[5], "dec": max(1, info[6]),
            "triggered": bool(info[7] & 1),
            "stale": bool(info[7] & 0x80000000),
        }
        return list(a1[:got]), list(a2[:got]), d

    def read_frame_locked_arrays(self, n=DEPTH):
        """Same transaction as read_frame_locked(), retaining ctypes arrays.

        The UI can pass these buffers directly to PL/C processing without
        converting 8192 samples to Python integers every frame.
        """
        if not self.hw:
            x, y = self._sim_frame(n)
            a1 = (ctypes.c_ushort * n)(*x)
            a2 = (ctypes.c_ushort * n)(*y)
            return a1, a2, {"seq": 0, "bank": 0, "start": 0, "count": n,
                            "trig_index": n // 2, "lost": 0, "dec": 1,
                            "triggered": True, "stale": False}
        a1 = (ctypes.c_ushort * n)()
        a2 = (ctypes.c_ushort * n)()
        info = (ctypes.c_uint * 8)()
        got = self.lib.sd_read_frame_locked(a1, a2, ctypes.c_int(n), info)
        if got <= 0:
            return None, None, {"error": got}
        d = {"seq": info[0], "bank": info[1], "start": info[2],
             "count": info[3], "trig_index": info[4], "lost": info[5],
             "dec": max(1, info[6]), "triggered": bool(info[7] & 1),
             "stale": bool(info[7] & 0x80000000)}
        return a1, a2, d

    @staticmethod
    def _window_ptr(data, start=0):
        if isinstance(data, ctypes.Array):
            return ctypes.cast(ctypes.byref(data, int(start) * 2),
                               ctypes.POINTER(ctypes.c_ushort))
        arr = (ctypes.c_ushort * len(data))(*data)
        return arr, ctypes.cast(ctypes.byref(arr, int(start) * 2),
                                ctypes.POINTER(ctypes.c_ushort))

    def measure_fast(self, data, dt, cal, hys=0, start=0, n=None):
        """Percentile + hysteresis measurement in native code (PL-compatible)."""
        if n is None:
            n = len(data) - start
        n = max(0, min(int(n), len(data) - int(start)))
        if n < 8 or not self.hw:
            from scope_processing import measure
            return measure(list(data)[start:start + n], dt, cal, hys or None)
        keep = None
        p = self._window_ptr(data, start)
        if isinstance(p, tuple):
            keep, p = p
        out = (ctypes.c_double * 16)()
        self.lib.sd_measure_ex(p, n, int(hys or 0), out)
        raw_min, raw_max = int(out[0]), int(out[1])
        lo, hi, center = int(out[2]), int(out[3]), int(out[6])
        period_pts = float(out[9]) if out[9] > 0 else None
        gain_probe = cal.gain * cal.probe
        result = {
            "n": n, "min": raw_min, "max": raw_max,
            "min_robust": lo, "max_robust": hi,
            "mid": center, "mean": float(out[4]), "rms": float(out[5]),
            "pp": hi - lo, "pp_raw": raw_max - raw_min,
            "vpp": (hi - lo) * 10.0 / 1023.0 * gain_probe,
            "vpp_raw": (raw_max - raw_min) * 10.0 / 1023.0 * gain_probe,
            "vmax": cal.to_volt(hi), "vmin": cal.to_volt(lo),
            "vmean": cal.to_volt(float(out[4])), "hys": int(out[7]),
            "edges": int(out[8]), "period_pts": period_pts,
            "period_spread": float(out[10]), "locked": bool(out[12]),
            "clip_low": int(out[13]), "clip_high": int(out[14]),
        }
        result["clipped"] = (result["clip_low"] >= max(4, n // 200) or
                             result["clip_high"] >= max(4, n // 200))
        if period_pts:
            result["period"] = period_pts * dt
            result["freq"] = 1.0 / result["period"]
        if out[11] >= 0:
            result["duty"] = float(out[11])
        if hi - lo < 8:
            result["locked"] = False
            result["note"] = "信号太小"
        elif not result.get("freq"):
            result["note"] = "未锁定"
        return result

    def envelope_fast(self, data, cols, start=0, n=None):
        if n is None:
            n = len(data) - start
        n = max(1, min(int(n), len(data) - int(start)))
        amin = (ctypes.c_ushort * cols)()
        amax = (ctypes.c_ushort * cols)()
        keep = None
        p = self._window_ptr(data, start)
        if isinstance(p, tuple):
            keep, p = p
        self.lib.sd_envelope(p, n, amin, amax, cols, 0)
        return amin, amax

    def draw_trace_fast(self, buf_ptr, w, h, data, n, color, cy, lpp,
                        start=0):
        keep = None
        p = self._window_ptr(data, start)
        if isinstance(p, tuple):
            keep, p = p
        self.lib.sd_draw_trace(buf_ptr, w, h, p, n, color,
                               ctypes.c_double(cy), ctypes.c_double(lpp))

    def pl_frame_stats(self):
        """SCP4 per-frame PL results. Older bitstreams return None."""
        if not self.hw or int(self.lib.sd_version()) < 0x53435034:
            return None
        result = []
        for sv, ev in ((self.lib.sd_stats1(), self.lib.sd_edge1()),
                       (self.lib.sd_stats2(), self.lib.sd_edge2())):
            result.append({"min": sv & 0x3FF, "max": (sv >> 10) & 0x3FF,
                           "clip_low": bool((sv >> 30) & 1),
                           "clip_high": bool((sv >> 31) & 1),
                           "edge_span_ticks": ev & 0xFFFFFF,
                           "edge_count": (ev >> 24) & 0xFF})
        return result

    # ---------------- 步骤3：Roll 连续读取 ----------------
    def read_roll(self, n=128):
        """Roll 模式下取【最新 n 个连续点】（n 建议 64~256）。

        PL 的 write_ptr 一直在环形前进、采样连续不停，所以这里拿到的
        是真正相邻的连续数据，滚动不会跳变、不会缺段。
        """
        if not self.hw:
            return self._sim_frame(n), self._sim_frame(n)
        a1 = (ctypes.c_ushort * n)()
        a2 = (ctypes.c_ushort * n)()
        got = self.lib.sd_read_roll(a1, a2, ctypes.c_int(n))
        if got <= 0:
            return None, None
        return list(a1[:got]), list(a2[:got])

    # ---------------- 阶段4：窗口 + 统计 ----------------
    def set_window(self, start, length):
        """告诉 PL 显示窗口，包络只在这段上算（横轴才与 Time/div 一致）"""
        if not self.hw:
            return
        try:
            self.lib.sd_set_window(ctypes.c_uint(int(start) & 0xFFF),
                                   ctypes.c_uint(int(length) & 0x1FFF))
        except Exception:
            pass

    def read_stats(self):
        """读 PL 流式统计（9 个寄存器）。返回 list 或 None。"""
        if not self.hw:
            return None
        out = (ctypes.c_uint * 16)()
        try:
            ok = self.lib.sd_read_stats(out)
        except Exception:
            return None
        if not ok:
            return None
        return list(out)

    # ---------------- 阶段4：PL 列包络 ----------------
    def read_envelope(self, cols=1008):
        """从 PL 直接取两通道列包络（每列 min/max）。

        PL 在采集时流式算好，PS 只做 2016 次单读事务；
        旧路径要逐点写指针+读数据共 8192 次，这里是 4 倍差距。
        返回 (mn1, mx1, mn2, mx2)，每个是长度 cols 的 list。
        """
        if not self.hw:
            f = self._sim_frame(cols)
            return f, f, f, f
        mn1 = (ctypes.c_ushort * cols)()
        mx1 = (ctypes.c_ushort * cols)()
        mn2 = (ctypes.c_ushort * cols)()
        mx2 = (ctypes.c_ushort * cols)()
        got = self.lib.sd_read_envelope(mn1, mx1, mn2, mx2, ctypes.c_int(cols))
        if got <= 0:
            return None, None, None, None
        return (list(mn1), list(mx1), list(mn2), list(mx2))

    def envelope_into(self, mn1, mx1, mn2, mx2, cols=1008):
        """把包络读进调用方提供的 ctypes 数组（避免建 list）。"""
        if not self.hw:
            return 0
        return self.lib.sd_read_envelope(mn1, mx1, mn2, mx2, ctypes.c_int(cols))

    # ---------------- 渲染 ----------------
    def render(self, buf, w, h, data=None, color=0x5AFFAA, ch=1,
               vlo=0, vhi=SAMPLE_MAX, yoff=0):
        """把一路采样渲染成 w*h*3 的 BGR 缓冲（每列 min/max 竖线）"""
        if data is None:
            data = self.ch1 if ch == 1 else self.ch2
        n = len(data)
        if n < 4 or w <= 0 or h <= 0:
            return False
        if self.hw and self.lib is not None:
            arr = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            smp = (ctypes.c_ushort * n)(*data)
            self.lib.sd_render(arr, ctypes.c_int(w), ctypes.c_int(h),
                               smp, ctypes.c_int(n), ctypes.c_uint(color),
                               ctypes.c_int(vlo), ctypes.c_int(vhi),
                               ctypes.c_int(yoff))
            return True
        # PC 上的纯 Python 兜底（慢，只为能看）
        cb, cg, cr = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        span = max(1, vhi - vlo)
        for px in range(w):
            a = px * n // w
            e = min(max(a + 1, (px + 1) * n // w) + 1, n)
            seg = data[a:e]
            if not seg:
                break
            lo, hi = min(seg), max(seg)
            y0 = (h - 1) - (hi - vlo) * (h - 1) // span + yoff
            y1 = (h - 1) - (lo - vlo) * (h - 1) // span + yoff
            if y1 <= y0:
                y1 = y0 + 1
            for y in range(max(0, y0), min(h - 1, y1) + 1):
                o = (y * w + px) * 3
                buf[o] = cb
                buf[o + 1] = cg
                buf[o + 2] = cr
        return True

    def hline(self, buf, w, h, y, color):
        if self.hw and self.lib is not None:
            arr = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
            self.lib.sd_hline(arr, ctypes.c_int(w), ctypes.c_int(h),
                              ctypes.c_int(y), ctypes.c_uint(color))
            return
        cb, cg, cr = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        if y < 0 or y >= h:
            return
        for x in range(w):
            o = (y * w + x) * 3
            buf[o] = cb
            buf[o + 1] = cg
            buf[o + 2] = cr

    def close(self):
        if self.lib:
            self.lib.sd_close()
            self.lib = None
            self.hw = False


def probe():
    """只探测，给别的地方用"""
    s = ScopeDual(verbose=False)
    ok = s.hw
    why = s.why
    s.close()
    return ok, why
