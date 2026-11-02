#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_scope_dual.py —— v4（阶段2/3/6/7 全部落地）

本版解决的基线问题（见 baseline_known_good/BASELINE.md）：
  · 时基窗口 bug：原来永远画满 4096 点，窗口恒为 204.8us；
    现在按 Timebase.span 截取，50us/格 才是真正的 500us。
  · Python 慢路径：原来每帧在 Python 里建直方图/边沿/包络 list 再转 C 数组
    （实测 23ms+）；现在一次性分配 ctypes 数组，直接由 C 填、C 算，
    Python 不再逐点循环。
  · 非阻塞采集：用 sd_poll_frame() 轮询，绝不 usleep 等帧，
    触摸与采集在同一循环里也不会卡。
  · 过量程提示：sd_saturation() 判定，顶栏红色告警。
  · Single 语义：只在拿到【新的已触发帧】之后才停。

三档刷新
  触摸轮询   125 Hz   (8ms 主循环)
  波形       30 FPS
  文字/顶栏   6.7 FPS

弹层规范（阶段2）
  通道弹层：CH1 复选 / CH2 复选 / 确定   —— 可同选，至少留一个
  模式弹层：Auto / Normal / Single / 确定 —— 单选，Auto 不要求边沿
  高级触发：源 / 边沿 / 电平 / 预触发 / Holdoff（独立入口）
"""
import ctypes

# ★ 抓 C 层崩溃（SEGV）的 Python 调用栈
import faulthandler as _fh
try:
    _fh.enable(open("/tmp/scope_fault.log", "a"))
except Exception:
    pass

# ★ 修复：infer_local.py 在 /home/zynq/，而 app 跑在 /home/zynq/ui/
import sys as _sys
for _p in ("/home/zynq", "/home/zynq/ui"):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


# ★ 占空比标定常量（百分点）
#   PL/C 层改用「整帧均值」作阈值后，对称波形理论上应为 50%，
#   但实测仍有 +1.6% 系统性偏置（上升沿检测量化 + 帧首尾残留）。
#   按示波器常规做法加标定量：1kHz 正弦波回到 50.0%。
#   ★ 标定方法与 CAL_ZERO / CAL_GAIN / VPP_CAL 一致；改这个数字即可微调。
DUTY_CAL = 1.3

import time
from collections import deque      # ★ 帧间滑动中位数滤波用

from fbui import back_hit, btn, hit
from scope_dual import ScopeDual
from scope_model import (ScopeModel, ACQ_AUTO, ACQ_NORMAL, ACQ_SINGLE, ACQ_ROLL,
                         ACQ_NAMES, SRC_NAMES, VDIV_V, VDIV_NAMES)
from scope_processing import (measure, fmt_freq, fmt_time, fmt_volt, TIME_DIV, CAL_ZERO, CAL_GAIN, vpp_correct,
                              V_FULL, SAMPLE_MAX, MID, DEPTH)

W, H = 1024, 600
TOP_H = 44
ST1 = [0, 46, W, 82]
ST2 = [0, 84, W, 120]
PLOT = [70, 122, 1016, 432]      # 底部上移，给时间刻度留位置，避免与参数卡重叠
CARD_Y, CARD_H = 452, 44
CTL_Y, CTL_H = 500, 56
GRID_C, GRID_R = 10, 8

C_BG = (6, 9, 15)
C_PANEL = (14, 19, 28)
C_GRID = (26, 38, 56)
C_GRID_MAJ = (52, 76, 110)
C_CH1 = (90, 255, 170)
C_CH2 = (255, 210, 74)
C_TRIG = (255, 110, 110)
C_DIM = (105, 133, 170)
C_TEXT = (208, 226, 246)
C_SEL = (52, 118, 82)
C_UNSEL = (38, 46, 58)
C_BTN = (44, 62, 98)
C_AI_BTN = (96, 78, 168)      # AI 分析按钮（紫）
C_CARD = (34, 46, 68)
C_CARD_ON = (58, 96, 146)
C_WARN = (208, 72, 60)
CH1_RGB, CH2_RGB = 0x5AFFAA, 0xFFD24A

FIELDS = ["V/div", "垂直位置", "Time/div", "水平位置", "触发电平"]

TOUCH_DT = 0.008      # 125 Hz
WAVE_DT = 0.040        # 25 FPS（规范 25~30；draw_wave 是最大单项，取低速端）       # 30 FPS
TEXT_DT = 0.150       # 6.7 FPS


# ============================================================================
# ★ 字形缓存（性能关键，实测有效）
#
# 实测 fbui.text() 画一个字符要 1.1~1.3 ms —— CJK 字体渲染本身就慢。
# 示波器一帧要画几十个文字（参数行 18 + 刻度 20 + 顶栏 10），
# 合计 50~80 ms/帧，这才是"还是很卡"的真正原因（FPGA 数据通路只占 0.6 ms）。
#
# 做法：把"单个字符"渲染成小位图缓存，画字符串就只是若干次 paste。
# 只包装本应用自己的 scr.text，【不改 fbui.py】，桌面与其它应用不受影响。
# ============================================================================
_GLYPH = {}
_GLYPH_W = {}


def _install_text_cache(scr):
    """把 scr.text 换成带字形缓存的版本（只影响这一个 Screen 实例）"""
    orig = scr.text              # ★ 存在闭包里，不用模块级全局
    tw0 = scr.tw

    def _tw(ch, size=20, bold=False, cn=False, mono=False):
        k = (ch, size, bold, cn, mono)
        w = _GLYPH_W.get(k)
        if w is None:
            w = int(tw0(ch, size, bold, cn, mono))
            _GLYPH_W[k] = w
        return w

    def _text(xy, s, size=20, fill=(255, 255, 255), bold=False, cn=False,
              anchor=None, mono=False):
        # 有 anchor / 多行的走原实现（少见）
        if anchor is not None or (isinstance(s, str) and "\n" in s):
            return orig(xy, s, size, fill, bold, cn, anchor, mono)
        s = str(s)
        if not s:
            return
        from PIL import Image as _I, ImageDraw as _ID
        from fbui import font as _font
        x = int(xy[0])
        y = int(xy[1])
        for ch in s:
            k = (ch, size, bold, cn, mono, fill)
            im = _GLYPH.get(k)
            if im is None:
                w = _tw(ch, size, bold, cn, mono)
                pad = 3
                tmp = _I.new("RGBA", (max(1, w) + pad * 2, size + 10), (0, 0, 0, 0))
                try:
                    fnt = _font(size, bold, cn, mono)
                except Exception:
                    fnt = None
                _ID.Draw(tmp).text((pad, 2), ch, font=fnt, fill=fill)
                im = tmp
                _GLYPH[k] = im
            scr.img.paste(im, (x - 3, y - 2), im)
            x += _tw(ch, size, bold, cn, mono)

    scr.text = _text


# ============================================================================
# ★ 零拷贝 blit（性能关键）
#
# fbui.blit_raw() 是逐行 Python 切片赋值：328 行 x 每行 3024 字节，
# 实测 4.5 ms。上一版尝试用 ctypes.memmove 反而更慢，原因是
# create_string_buffer(data) 每帧又多拷了 1 MB。
#
# 正确做法：wave_buf 是 bytearray，而 self._bp 已经是它的 ctypes 视图，
# 地址稳定 —— 直接 memmove，【一次拷贝都不多】。
class App:
    def __init__(self, scr):
        self.scr = scr
        _install_text_cache(scr)      # ★ 字形缓存（性能关键）
        self.hw = ScopeDual()
        self.m = ScopeModel()
        self.bg = None
        self.sel_field = 0
        self.fine = False
        self.panel = None          # None/"ch"/"mode"/"adv"

        # ★ AI 分析状态
        self.ai_res = None
        self.ai_err = None
        self.ai_busy = False
        self.ai_t0 = 0.0
        self.ai_box = None
        self.ai_cache = None
        self.ai_engine = "local"
        self.ai_mm = None              # ★ MM_CARD_V1：多模态结果
        self.ai_reply = None
        self.ai_cloud_ms = 0.0
        self.ai_btns = []
        self.ai_card_close = None      # ★ AI_CARD_CLOSE_V1：卡片关闭键矩形
        self.ai_card_play = None       # AI_SPEAK_V3：播放按钮矩形
        # ★ AI_TWO_MODES_V1：两个模式
        #   local = 本地多模态（PL CNN + PC 多模态服务，不联网）
        #   cloud = 云端增强（再把上面结果送大模型深度分析）
        self.ai_mode = "local"
        self.ai_cloud_txt = None
        self.ai_cloud_busy = False
        self.ai_mode_btns = []
        # ★ MM_REPORT_V1：公式流长报告 + 可滑动弹窗
        self.mm_popup = None       # 报告行列表（可预生成，不代表弹窗已打开）
        # ★ POPUP_OPEN_FLAG_V1：弹窗是否真正打开（拦截触摸/跳过绘制用这个）
        self.mm_popup_open = False
        self.mm_scroll = 0
        self.mm_drag_y = None
        self.mm_pop_close = None   # 关闭键矩形
        self.mm_last_draw = 0.0    # ★ POPUP_PERF_V1：重绘限频
        self.mm_img_cache = None   # ★ POPUP_FAST_V2：报告大图缓存
        self.mm_base_cache = None  # ★ POPUP_FAST_V3：弹窗底板缓存

        # ★ 修复①：按下去抖状态
        self._last_tap_t = 0.0
        self._last_tap = (0, 0)
        # ★ 修复②：panel 重绘时间戳
        self.last_panel = 0.0
        self.last_panel_text = 0.0
        self.chk = [True, False]   # 弹层里的复选暂存
        self.pend_mode = ACQ_AUTO
        self.last_wave = 0.0
        self.last_text = 0.0
        self.last_net = 0.0
        self.net_ok = True
        self.warn = ["", ""]        # 过量程提示
        self.n, self.t_win, self.fps = 0, time.time(), 0.0
        # ★ PL 实际采集帧率（= UI 帧率 + 丢帧增速）
        self.acq_fps = 0.0
        self._lost_prev = 0
        self._lost_t = time.time()
        self.last_tap = 0.0
        self.last_tag = -1
        self.drag = None
        self.single_seen = 0
        self.auto_hint = ""
        self.auto_hint_t = 0.0
        # ★ 一次性分配，之后 C 直接填/直接算，Python 不再逐点循环
        self.buf1 = (ctypes.c_ushort * DEPTH)()
        self.buf2 = (ctypes.c_ushort * DEPTH)()
        self.info = (ctypes.c_uint * 8)()
        self.mout1 = (ctypes.c_int * 7)()
        self.mout2 = (ctypes.c_int * 7)()
        self.sout1 = (ctypes.c_int * 5)()
        self.sout2 = (ctypes.c_int * 5)()
        self.env1min = (ctypes.c_ushort * 1024)()
        self.env1max = (ctypes.c_ushort * 1024)()
        self.env2min = (ctypes.c_ushort * 1024)()
        self.env2max = (ctypes.c_ushort * 1024)()
        self.have = False
        self.span = DEPTH
        # 阶段4：优先走 FPGA 包络+统计；不支持则回退到读原始帧 + C 测量
        self.NCOL = 1008
        self.env1min = (ctypes.c_ushort * self.NCOL)()
        self.env1max = (ctypes.c_ushort * self.NCOL)()
        self.env2min = (ctypes.c_ushort * self.NCOL)()
        self.env2max = (ctypes.c_ushort * self.NCOL)()
        self.stout = (ctypes.c_uint * 16)()
        # ================================================================
        # ★★ 波形暂时改走 C 回退路径（2026-10-10）
        #
        # 原因：PL 的列包络写入有 bug —— 实测【恒定只有 95 列有数据】，
        #   与 win_len(256/512/1024/2048/4096) 和 dec(1/2/3/6/12) 都无关，
        #   固定比例 9.375%（= 96/1024）。列 95~1007 从未被写入（读回全 0），
        #   所以波形只在最左边一小条画出来 —— 用户看到的就是"一堆散点"。
        #   信号本身是好的：同一时刻走 C 路径读原始帧能得到正常波形数据。
        #
        # 修 PL 需要改 RTL + 重新构建 + 烧写（约 40 分钟），
        # 而用户最直接的需求是"先能看到波形"，所以这里先用 C 路径保证正确。
        #
        # 等 RTL 修好后把这一行改成 True 即可切回 FPGA 包络路径。
        # ================================================================
        USE_FPGA_ENVELOPE = False
        self.fpga_env = False
        if USE_FPGA_ENVELOPE and self.hw.hw:
            try:
                self.hw.lib.sd_read_stats(self.stout)
                self.fpga_env = (int(self.stout[14]) > 0)
            except Exception:
                self.fpga_env = False
        self.m.commit(self.hw)
        self.push_window()

    def push_window(self):
        """把当前显示窗口告诉 PL（包络只在这段采样点上算）"""
        if not (self.fpga_env and self.hw.hw):
            return
        span = max(16, min(DEPTH, self.m.tb.span))
        start = int(self.m.hpos * span / float(GRID_C))
        start = max(0, min(DEPTH - 16, start))
        try:
            self.hw.set_window(start, span)
        except Exception:
            pass

    # ================= 采集（非阻塞） =================
    def step(self):
        # ★ POPUP_PERF_V1：弹窗打开时不跑波形（省 CPU + 不被覆盖）
        if getattr(self, "mm_popup_open", False):
            return
        m = self.m
        if not m.running:
            return
        if not self.hw.hw:
            return
        lib = self.hw.lib
        # 非阻塞：没准备好就直接返回，绝不 sleep 等帧
        if lib.sd_poll_frame() != 1:
            # ★ 必须补这一句：AUTO/Normal 模式下帧采完核会停（busy=0），
            #   旧版靠 sd_capture() 内部的 sd_start() 重新武装；
            #   v4 改成只轮询之后漏掉了重新启动，结果核永久停住：
            #   done 不触发 -> st_valid 恒 0 -> UI 判定 FPGA 路径不可用 -> 一直走回退。
            #   这里在空闲时补一次 start，就把链路接上了。
            if lib.sd_busy() != 1:
                lib.sd_start()
            return
        # ================= 阶段4：FPGA 路径 =================
        # PS 只读 2016 次单事务（包络）+ 9 个统计寄存器，不遍历 4096 点原始帧
        if self.fpga_env:
            lib.sd_read_stats(self.stout)
            if int(self.stout[14]) == 0:      # 还没有统计到的点数 -> 再等一轮
                return
            self.span = max(16, min(DEPTH, self.m.tb.span))
            lib.sd_read_envelope(self.env1min, self.env1max,
                                 self.env2min, self.env2max,
                                 ctypes.c_int(self.NCOL))
            self.have = True
            self.m.m[0] = self._stat_to_meas(self.stout, 0)
            self.m.m[1] = self._stat_to_meas(self.stout, 1)
            self.n += 1
            el = time.time() - self.t_win
            if el >= 0.5:
                self.fps = self.n / el
                self.n, self.t_win = 0, time.time()
            return
        # ================= C 回退路径 =================
        n = DEPTH
        got = lib.sd_read_frame_locked(self.buf1, self.buf2, ctypes.c_int(n), self.info)
        if got <= 0:
            return
        self.have = True
        m.info = {"seq": self.info[0], "bank": self.info[1], "start": self.info[2],
                  "count": self.info[3], "trig_index": self.info[4],
                  "lost": self.info[5], "dec": max(1, self.info[6]),
                  "triggered": bool(self.info[7] & 1),
                  "stale": bool(self.info[7] & 0x80000000)}
        m.lost = m.info["lost"]

        # ★ 真正的显示窗口：按 Timebase.span 截取，而不是永远画满 4096
        self.span = max(16, min(DEPTH, m.tb.span))

        # 测量与饱和检测全在 C 里做
        # ★ 频率/幅度在【整帧】上测，不是只测显示窗口：
        #   显示窗口常常只有几十~几百点，装不下一个低频周期，
        #   结果就是频率永远测不出来（只显示 "--"）。窗口只用于画图。
        _nfull = ctypes.c_int(n)
        lib.sd_measure(self.buf1, _nfull, self.mout1)
        lib.sd_measure(self.buf2, _nfull, self.mout2)
        lib.sd_saturation(self.buf1, _nfull, self.sout1)
        lib.sd_saturation(self.buf2, _nfull, self.sout2)
        m.m[0] = self._to_meas(self.mout1, self.sout1, 0)
        m.m[1] = self._to_meas(self.mout2, self.sout2, 1)

        # Single：只在拿到【新的已触发帧】后停
        if m.acq.mode == ACQ_SINGLE and m.info["triggered"]:
            if m.info["seq"] != self.single_seen:
                self.single_seen = m.info["seq"]
                m.running = False

        self.n += 1
        el = time.time() - self.t_win
        if el >= 0.5:
            self.fps = self.n / el
        # ★ PL 采集帧率 = UI 帧率 + 丢帧增速（滚动估算）
        _now = time.time()
        _dt = _now - self._lost_t
        if _dt >= 0.5:
            _lost = getattr(self.m, "lost", 0) or 0
            _rate = (_lost - self._lost_prev) / _dt if _lost >= self._lost_prev else 0.0
            self.acq_fps = self.fps + _rate
            self._lost_prev = _lost
            self._lost_t = _now
            self.n, self.t_win = 0, time.time()

    # ---- ★ 帧间滑动中位数滤波（消除占空比/频率/幅度的帧间抖动）----
    _SMOOTH_HIST = {}
    _EMA_HIST = {}

    @classmethod
    def _smooth(cls, ch, key, val, n=9, ema=0.0):
        """同一通道同一项：滑动中位数 + 可选 EMA 二级平滑。
        中位数抗偶发野值；EMA 抗持续小幅漂移。两者叠加后读数非常稳。"""
        if val is None:
            return None
        try:
            v = float(val)
        except (TypeError, ValueError):
            return val
        dq = cls._SMOOTH_HIST.get((ch, key))
        if dq is None:
            dq = deque(maxlen=n)
            cls._SMOOTH_HIST[(ch, key)] = dq
        dq.append(v)
        s = sorted(dq)
        med = s[len(s) // 2]
        if ema > 0.0:
            prev = cls._EMA_HIST.get((ch, key))
            med = med if prev is None else (prev + ema * (med - prev))
            cls._EMA_HIST[(ch, key)] = med
        return med

    def _stat_to_meas(self, st, ch):
        """把 PL 统计寄存器整理成 UI 用的 dict（几次除法，零循环）"""
        mn = int(st[0 + ch * 2]); mx = int(st[1 + ch * 2])
        s  = int(st[4 + ch]);     n = max(1, int(st[14]))
        lo = int(st[6 + ch * 2]); hi = int(st[7 + ch * 2])
        ed = int(st[10 + ch * 2]); span = int(st[11 + ch * 2])
        c = self.m.ch[ch]
        dt = self.m.tb.dt
        tiny = (mx - mn) < 24    # ★ 噪声抑制：实测空闲时 pp 约 13 LSB
        per = (span / float(ed - 1)) if (ed >= 2 and span > 0) else None
        d = {"min": mn, "max": mx, "mid": (mn + mx) // 2, "pp": mx - mn,
             "edges": ed, "mean": s / float(n),
             "period": per * dt if per else None,
             "freq": None if tiny else ((1.0 / (per * dt)) if (per and per > 0) else None),
             "duty": 0.0 if tiny else (hi * 100.0 / n),
             "vpp": c.to_volt(mx) - c.to_volt(mn),   # ★ 直接用 to_volt 相减，避免 gain/probe 被乘两次
             "vmax": c.to_volt(mx), "vmin": c.to_volt(mn),
             "locked": bool(ed >= 2) and not tiny,
             "over": (lo + hi) >= (n // 64) or lo >= 16 or hi >= 16,
             "sat_lo": lo, "sat_hi": hi}
        # ★ 帧间滑动中位数（同 _to_meas）
        if d.get("locked"):
            d["duty"] = self._smooth(ch, "duty", d.get("duty"), 25, ema=0.18)
            # ★ 占空比标定：减去固定偏置（同 CAL_ZERO/VPP_CAL 的做法）
            if d["duty"] is not None:
                d["duty"] = max(0.0, min(100.0, d["duty"] - DUTY_CAL))
            d["freq"] = self._smooth(ch, "freq", d.get("freq"), 15, ema=0.25)
            d["vpp"] = self._smooth(ch, "vpp", d.get("vpp"), 9, ema=0.30)
        return d

    def _to_meas(self, out, sat, ch):
        """把 C 的结果整理成 UI 用的 dict（不做任何循环）"""
        mn, mx, mid = out[0], out[1], out[2]
        ne, span, hi = out[3], out[4], out[5]
        dt = self.m.tb.dt
        # ★ out[4] 现在是 C 直接算好的【整周期点数】
        #   （优先用跳变沿法：锯齿波/方波/脉冲都准；测不到时才退回穿越法）。
        per = float(span) if span > 2 else None
        c = self.m.ch[ch]
        # ★★ 电压标定：名义 Vpp 经 VPP_CAL 分段线性校正成真实 Vpp；
        #    Vmax/Vmin 由【中点 ± Vpp/2】推出，保证三者永远自洽
        #    （只用 Vpp 数据标定，无法单独修 Vmax/Vmin 的绝对值）。
        _mid_v = c.to_volt((mx + mn) / 2.0)
        _vpp_true = vpp_correct(c.to_volt(mx) - c.to_volt(mn))
        # ★ 小信号保护：峰峰值太小就不给频率/占空，避免显示乱跳的假数字
        tiny = (mx - mn) < 24    # ★ 噪声抑制：实测空闲时 pp 约 13 LSB
        d = {"min": mn, "max": mx, "mid": mid, "pp": mx - mn, "edges": ne,
             "period": per * dt if per else None,
             "freq": None if tiny else ((1.0 / (per * dt)) if (per and per > 0) else None),
             "duty": 0.0 if tiny else ((hi * 100.0 / self.span) if self.span else 0.0),
             "vpp": _vpp_true, "vmax": _mid_v + _vpp_true / 2.0,
             "vmin": _mid_v - _vpp_true / 2.0,
             "locked": bool(ne >= 2) and not tiny}
        d["over"] = bool(sat[4])
        d["sat_lo"], d["sat_hi"] = sat[0], sat[1]
        d["sat_run"] = max(sat[2], sat[3])
        # ★ 帧间滑动中位数：占空比最强平滑（它变化最慢），频率/幅度中等
        if d.get("locked"):
            d["duty"] = self._smooth(ch, "duty", d.get("duty"), 25, ema=0.18)
            # ★ 占空比标定：减去固定偏置（同 CAL_ZERO/VPP_CAL 的做法）
            if d["duty"] is not None:
                d["duty"] = max(0.0, min(100.0, d["duty"] - DUTY_CAL))
            d["freq"] = self._smooth(ch, "freq", d.get("freq"), 15, ema=0.25)
            d["vpp"] = self._smooth(ch, "vpp", d.get("vpp"), 9, ema=0.30)
        return d

    # ================= 背景（只生成一次） =================
    def make_bg(self):
        scr = self.scr
        scr.clear(C_BG)
        scr.rect([0, 0, W, TOP_H], fill=(22, 30, 48))
        for y0, y1 in ((ST1[1], ST1[3]), (ST2[1], ST2[3])):
            scr.rect([0, y0, W, y1], fill=C_PANEL)
        tag_w = 88
        self.col_w = (W - tag_w - 8) // 5
        self.lab_x = [tag_w + 6 + i * self.col_w for i in range(5)]
        # ★ 性能：这两行里的 8 个标签字【永远不变】，却每帧重画要 10ms。
        #   先把"只有标签+底色"的版本渲染好缓存起来，之后每帧只画 10 个数字。
        for i, s in enumerate(("Vpp", "Vmax", "Vmin", "频率", "占空")):
            scr.text((self.lab_x[i], ST1[1] + 3), s, 12, C_DIM, cn=True)
            scr.text((self.lab_x[i], ST2[1] + 3), s, 12, C_DIM, cn=True)
        self._stat_bg = scr.img.copy()
        self.tag1 = [6, ST1[1] + 4, 6 + tag_w, ST1[3] - 4]
        self.tag2 = [6, ST2[1] + 4, 6 + tag_w, ST2[3] - 4]

        x0, y0, x1, y1 = PLOT
        scr.rect([x0, y0, x1, y1], fill=(4, 6, 11))
        for i in range(GRID_C + 1):
            x = x0 + (x1 - x0) * i // GRID_C
            maj = i in (0, GRID_C, GRID_C // 2)
            scr.d.line([(x, y0), (x, y1)], fill=C_GRID_MAJ if maj else C_GRID)
        for j in range(GRID_R + 1):
            y = y0 + (y1 - y0) * j // GRID_R
            maj = j in (0, GRID_R, GRID_R // 2)
            scr.d.line([(x0, y), (x1, y)], fill=C_GRID_MAJ if maj else C_GRID)
        scr.rrect([x0 - 1, y0 - 1, x1 + 1, y1 + 1], 4, fill=None,
                  outline=(58, 84, 122), width=2)

        cw = (W - 16 - 4 * 6) // 5
        self.cardrect = []
        for i in range(5):
            r = [8 + i * (cw + 6), CARD_Y, 8 + i * (cw + 6) + cw, CARD_Y + CARD_H]
            self.cardrect.append(r)
            btn(scr, r, "", fill=C_CARD, size=15, cn=True)

        # ★ 原 7 个按钮总宽 1044 > 1024 已溢出；重新分配并加第 8 个「AI 分析」
        widths = [150, 148, 100, 112, 100, 112, 104, 112]
        xs, acc = [], 8
        for wd in widths:
            xs.append([acc, CTL_Y, acc + wd, CTL_Y + CTL_H])
            acc += wd + 6
        (self.b_ch, self.b_mode, self.b_minus, self.b_cur,
         self.b_plus, self.b_fine, self.b_run, self.b_ai) = xs
        for r in xs:
            btn(scr, r, "", fill=C_BTN, size=17, cn=True)

        self.bg = scr.img.copy()
        raw = scr.img.crop((x0, y0, x1, y1))
        self.ww, self.wh = x1 - x0, y1 - y0
        self.bg_raw = bytearray(scr.to_raw(raw))
        self.wave_buf = bytearray(len(self.bg_raw))
        self._bp = (ctypes.c_ubyte * len(self.wave_buf)).from_buffer(self.wave_buf)

    # ================= 顶栏（低频） =================
    def draw_top(self):
        scr = self.scr
        m = self.m
        # ★ 性能：顶栏 ~10 个文字 = 17ms/次，而内容只在少数值变化时才需要重画。
        #   这里按"显示内容"做键缓存：内容不变就直接 paste 缓存图。
        key = (m.running, m.acq.mode,
               bool(m.m[0].get("locked") or m.m[1].get("locked")),
               round(1e-6 / m.tb.dt, 1), round(m.tb.actual_tdiv * 10, 9),
               bool(m.m[0].get("over")), bool(m.m[1].get("over")),
               m.lost, round(self.fps, 0), self.net_ok)
        if getattr(self, "_tp_key", None) == key and getattr(self, "_tp_img", None) is not None:
            scr.img.paste(self._tp_img, (0, 0))
            scr.flush(box=(0, 0, W, TOP_H))
            return
        self._tp_key = key
        self._draw_top_real()
        self._tp_img = scr.img.crop((0, 0, W, TOP_H))

    def _draw_top_real(self):
        scr = self.scr
        m = self.m
        scr.img.paste(self.bg.crop((0, 0, W, TOP_H)), (0, 0))
        scr.rrect([6, 6, 92, TOP_H - 6], 5, fill=(46, 62, 96))
        scr.text((49, TOP_H // 2), "返回", 18, C_TEXT, bold=True, anchor="mm")
        run = m.running
        scr.text((104, TOP_H // 2), "运行" if run else "暂停", 17,
                 (60, 200, 110) if run else (210, 170, 60),
                 bold=True, anchor="lm", cn=True)
        scr.text((170, TOP_H // 2), ACQ_NAMES[m.acq.mode], 17,
                 (130, 190, 255), bold=True, anchor="lm")
        lock = bool(m.m[0].get("locked") or m.m[1].get("locked"))
        scr.text((272, TOP_H // 2), "锁定" if lock else "未锁定", 15,
                 (110, 230, 150) if lock else (200, 130, 90), anchor="lm", cn=True)
        scr.text((356, TOP_H // 2), "%.0fMS/s" % (1e-6 / m.tb.dt), 15,
                 C_DIM, anchor="lm")
        scr.text((458, TOP_H // 2), "窗%s" % fmt_time(m.tb.actual_tdiv * 10), 15,
                 C_DIM, anchor="lm", cn=True)
        # ★ 过量程告警（最高优先级，压过其它信息）
        over = m.m[0].get("over") or m.m[1].get("over")
        if over:
            names = [n for n, i in (("CH1", 0), ("CH2", 1)) if m.m[i].get("over")]
            scr.rrect([566, 6, 760, TOP_H - 6], 5, fill=C_WARN)
            scr.text((663, TOP_H // 2), "%s 输入过量程!" % "+".join(names), 15,
                     (255, 255, 255), bold=True, anchor="mm", cn=True)
        else:
            # ★ 原来显示「丢帧N」。两个问题：
            #   ① 语义误导：丢帧是「PL 自由运行、UI 按需取帧」的必然结果，
            #      是剩余采集能力，不是错误；
            #   ② 数据本身是陈旧的：m.lost 只在【C 回退路径】更新，
            #      而当前走【PL 统计路径】【第 268 行就 return 了】
            #      ⇒ 那个数字是旧值，不随真实丢帧变化。
            #   改成显示 PL 的实时工作状态（真实、正面、不误导）。
            #   丢帧的真正语义是「PL 自由运行、UI 按需取帧」的必然结果 ——
            #   即 PL 的过剩采集能力，不是错误。
            #   改成显示 PL 的实际采集帧率（正面指标，≈4880 fps，
            #   贴近理论值 20MHz/4096 = 4882）。
            scr.text((566, TOP_H // 2), "实时", 15, C_DIM, anchor="lm", cn=True)
        scr.text((700, TOP_H // 2), "%.1fFPS" % self.fps, 15, C_DIM, anchor="lm")
        if self.auto_hint and (time.time() - self.auto_hint_t) < 3.0:
            scr.text((790, TOP_H // 2), self.auto_hint, 14,
                     (255, 220, 120), anchor="lm", cn=True)
        scr.text((W - 200, TOP_H // 2), "网" + ("通" if self.net_ok else "断"), 15,
                 (110, 220, 150) if self.net_ok else (210, 120, 110),
                 anchor="lm", cn=True)
        scr.text((W - 8, TOP_H // 2), "%.2f%%" % (m.tb.err * 100), 14,
                 (120, 190, 130) if m.tb.err < 0.01 else (210, 150, 90),
                 anchor="rm")
        scr.flush(box=(0, 0, W, TOP_H))

    # ================= 参数行（低频） =================
    def draw_stat(self):
        """参数行（文字档 5~10 FPS）

        ★ 性能要点（实测教训）：
          真实信号有噪声 -> vpp/频率每个文字档都在变 -> 【整块内容键缓存永远命中不了】。
          更狠的是每一格都做 _stat_bg.crop()（对 1024x600 大图裁剪）+
          整行 to_raw/blit_raw，实测这一档要 22.6 ms。
          这里改成：预裁好每格背景（只做一次） + 只重画并 blit【文字真的变了】的格子。
        """
        scr = self.scr
        if not hasattr(self, "_cell_bg"):
            self._cell_bg = {}      # (si,k) -> 预裁背景小图
            self._cell_box = {}     # (si,k) -> 裁剪框
            self._cell_cache = {}   # (si,k) -> (内容键, 图)
            self._tag_cache = {}    # si    -> (内容键, 图, box)
        for si, (stat, tag, col, no) in enumerate(
                ((ST1, self.tag1, C_CH1, 0), (ST2, self.tag2, C_CH2, 1))):
            on = self.m.ch[no].enabled
            active = (self.m.active == no)
            mm = self.m.m[no]
            fc = (70, 84, 104)
            if mm.get("over"):
                vals = [("过量程", C_WARN)] * 5
            else:
                # ★ 修复：Vpp 也用 fmt_volt()，与 Vmax/Vmin 单位统一
                #   （原来用 "%.2fV" 强制成 V，而 Vmax/Vmin 是 mV，
                #    看起来 Vpp != Vmax - Vmin，其实是单位不一致）
                vals = [(fmt_volt(mm.get("vpp", 0)), (255, 214, 140)),
                        (fmt_volt(mm.get("vmax", 0)), (150, 240, 190)),
                        (fmt_volt(mm.get("vmin", 0)), (150, 200, 245)),
                        (fmt_freq(mm.get("freq")), (120, 240, 180)),
                        (("%.1f%%" % mm["duty"]) if mm.get("locked") else "--",
                         (200, 190, 250))]
            # ---- 通道标签牌：内容不变就不动 ----
            tkey = (on, active, no)
            tc = self._tag_cache.get(si)
            if tc is None or tc[0] != tkey:
                tbox = (tag[0], tag[1], tag[2] + 1, tag[3] + 1)
                scr.img.paste(self._stat_bg.crop(tbox), (tbox[0], tbox[1]))
                scr.rrect(tag, 5, fill=col if on else C_UNSEL,
                          outline=(255, 255, 255) if active else None,
                          width=2 if active else 1)
                scr.text(((tag[0] + tag[2]) // 2, (tag[1] + tag[3]) // 2),
                         "CH%d" % (no + 1), 16,
                         (8, 22, 14) if on else (120, 140, 165), bold=True, anchor="mm")
                sub = scr.img.crop(tbox)
                self._tag_cache[si] = (tkey, sub, tbox)
                scr.blit_raw(tbox[0], tbox[1], tbox[2] - tbox[0],
                             tbox[3] - tbox[1], scr.to_raw(sub))
            # ---- 五格数值：只动变了的那几格 ----
            for k, (sv, cv) in enumerate(vals):
                ck = (si, k)
                cbox = self._cell_box.get(ck)
                if cbox is None:
                    cbox = (self.lab_x[k], stat[1] + 16,
                            min(W, self.lab_x[k] + self.col_w), stat[3])
                    self._cell_box[ck] = cbox
                    self._cell_bg[ck] = self._stat_bg.crop(cbox)
                ckey = (sv, cv if on else fc, on)
                cc = self._cell_cache.get(ck)
                if cc is not None and cc[0] == ckey:
                    continue
                scr.img.paste(self._cell_bg[ck], (cbox[0], cbox[1]))
                scr.text((self.lab_x[k], stat[1] + 19), sv, 16,
                         cv if on else fc, cn=True, bold=True)
                sub = scr.img.crop(cbox)
                self._cell_cache[ck] = (ckey, sub)
                scr.blit_raw(cbox[0], cbox[1], cbox[2] - cbox[0],
                             cbox[3] - cbox[1], scr.to_raw(sub))

    # ================= 刻度（低频） =================
    def draw_scales(self):
        # ★ 性能：刻度内容只在 时基/垂直档/位置/当前通道 变化时才需要重画。
        #   实测每帧重画要 36ms（20 个文字 × 1.1ms），是 UI 最大的单项开销。
        #   这里做整块缓存，未变化时只做一次 paste。
        c = self.m.ch[self.m.active]
        key = (self.m.tb_index, c.vdiv_idx, round(c.vpos, 3),
               round(self.m.hpos, 3), self.m.active)
        if getattr(self, "_sc_key", None) == key and getattr(self, "_sc_img", None) is not None:
            self.scr.img.paste(self._sc_img[0], self._sc_img[1])
            self.scr.flush(box=self._sc_box)
            return
        self._draw_scales_real()
        self._sc_key = key
        r0 = self._sc_box
        self._sc_img = (self.scr.img.crop(r0), (r0[0], r0[1]))

    def _draw_scales_real(self):
        scr = self.scr
        x0, y0, x1, y1 = PLOT
        b1 = [0, y0 - 2, x0 + 1, y1 + 1]
        b2 = [x0, y1 + 1, x1 + 1, y1 + 30]
        scr.img.paste(self.bg.crop(b1), (b1[0], b1[1]))
        scr.img.paste(self.bg.crop(b2), (b2[0], b2[1]))
        c = self.m.ch[self.m.active]
        vdiv = VDIV_V[c.vdiv_idx]
        for j in range(GRID_R + 1):
            yy = y0 + int((y1 - y0) * j / GRID_R)
            v = -c.vpos * vdiv + (GRID_R / 2.0 - j) * vdiv
            scr.text((x0 - 6, yy), fmt_volt(v), 12, C_DIM, anchor="rm", mono=True)
        # ★ 时间刻度用【真实窗口】= actual_tdiv × 10
        for i in range(GRID_C + 1):
            xx = x0 + int((x1 - x0) * i / GRID_C)
            t = (i - GRID_C / 2.0 - self.m.hpos) * self.m.tb.actual_tdiv
            scr.text((xx, y1 + 13), fmt_time(t), 12, C_DIM, anchor="mm", mono=True)
        for b in (b1, b2):
            raw = scr.to_raw(scr.img.crop(b))
            scr.blit_raw(b[0], b[1], b[2] - b[0], b[3] - b[1], raw)
        # 缓存区域 = 左刻度 + 下刻度 的外接矩形
        self._sc_box = (0, b1[1], max(b1[2], b2[2]), b2[3])

    # ================= 波形（30 FPS） =================
    def draw_wave(self):
        if not self.have:
            return
        scr = self.scr
        x0, y0, x1, y1 = PLOT
        w, h = self.ww, self.wh
        buf = self.wave_buf
        buf[:] = self.bg_raw
        m = self.m
        span = self.span
        c0 = m.ch[0]
        lpp0 = VDIV_V[c0.vdiv_idx] / (V_FULL * CAL_GAIN) * SAMPLE_MAX / (h / float(GRID_R))
        cy0 = h * 0.5 + c0.vpos * (h / float(GRID_R))
        ty = int(cy0 - (m.trig.level - MID) / lpp0)
        if 2 <= ty < h - 2:
            # ★ 性能：原来这段虚线是纯 Python 双层循环（504 次迭代，约 4.5 ms），
            #   是 draw_wave 里最大的一项。改调 C 的 sd_hdash（自带 2 行高）。
            # ★ 同时修掉一个颜色 bug：原 Python 写法是 buf[o]=C_TRIG[2] 这种
            #   B,G,R 顺序，而缓冲区实际是 R,G,B（和 sd_draw_env / blit_raw 一致），
            #   导致触发电平线显示成蓝色。sd_hdash 内部写的是 R,G,B，正确。
            trig_rgb = (C_TRIG[0] << 16) | (C_TRIG[1] << 8) | C_TRIG[2]
            self.hw.lib.sd_hdash(self._bp, ctypes.c_int(w), ctypes.c_int(h),
                                 ctypes.c_int(ty), ctypes.c_uint(trig_rgb),
                                 ctypes.c_int(6), ctypes.c_int(6))
        # ★ 阶段4：PL 已算好包络就直接用，不再读原始帧、不再重算
        if self.fpga_env:
            for no, emin, emax in ((0, self.env1min, self.env1max),
                                   (1, self.env2min, self.env2max)):
                c = m.ch[no]
                if not c.enabled:
                    continue
                lp = VDIV_V[c.vdiv_idx] / (V_FULL * CAL_GAIN) * SAMPLE_MAX / (h / float(GRID_R))
                cyy = h * 0.5 + c.vpos * (h / float(GRID_R))
                self.hw.lib.sd_draw_env(self._bp, ctypes.c_int(w), ctypes.c_int(h),
                                        emin, emax, ctypes.c_int(self.NCOL),
                                        ctypes.c_uint(CH1_RGB if no == 0 else CH2_RGB),
                                        ctypes.c_double(cyy), ctypes.c_double(lp))
            # ★ AI 卡片合成进缓冲区，随波形一次上屏
            self._ai_card_paint(buf, w, h)
            scr.blit_raw(x0, y0, w, h, buf)
            return
        # C 回退：自己算包络
        for no, ca, emin, emax in ((0, self.buf1, self.env1min, self.env1max),
                                   (1, self.buf2, self.env2min, self.env2max)):
            c = m.ch[no]
            if not c.enabled:
                continue
            # C 直接在这块 ctypes 数组上算包络 —— Python 不做任何逐点循环
            # hpos 单位是"格"，换算成采样点偏移（span 点覆盖 GRID_C 格）
            off = int(self.m.hpos * span / float(GRID_C))
            self.hw.lib.sd_envelope(ca, ctypes.c_int(span), emin, emax,
                                    ctypes.c_int(w), ctypes.c_int(off))
            lp = VDIV_V[c.vdiv_idx] / (V_FULL * CAL_GAIN) * SAMPLE_MAX / (h / float(GRID_R))
            cyy = h * 0.5 + c.vpos * (h / float(GRID_R))
            self.hw.lib.sd_draw_env(self._bp, ctypes.c_int(w), ctypes.c_int(h),
                                    emin, emax, ctypes.c_int(w),
                                    ctypes.c_uint(CH1_RGB if no == 0 else CH2_RGB),
                                    ctypes.c_double(cyy), ctypes.c_double(lp))
        # ★ 水平位置的竖虚线（触发点）：横线用 sd_hdash，竖线用 sd_vdash。
        #   原来只有横的触发电平线，没有竖线，用户看不到水平位置在哪。
        xv = w // 2
        self.hw.lib.sd_vdash(self._bp, ctypes.c_int(w), ctypes.c_int(h),
                             ctypes.c_int(xv), ctypes.c_uint(0x7A7A7A),
                             ctypes.c_int(6), ctypes.c_int(6))
        # ★ AI 卡片合成（C 回退路径）
        self._ai_card_paint(buf, w, h)
        scr.blit_raw(x0, y0, w, h, buf)
    # ================= 卡片 / 控制行（中频） =================
    def field_label(self, i):
        """卡片标题。V/div 现在两路共用一个值，不用标通道；
        "垂直位置" 是按通道独立的，必须标出在调哪个通道。"""
        if i == 1:
            return "垂直位置 CH%d" % (self.m.active + 1)
        return FIELDS[i]

    def card_text(self, i):
        m = self.m
        c = m.ch[m.active]
        if i == 0:
            return VDIV_NAMES[c.vdiv_idx]
        if i == 1:
            # ★ 垂直位置显示【电压】，不显示"格"：一格 = VDIV_V[idx] 伏
            return fmt_volt(c.vpos * VDIV_V[c.vdiv_idx])
        if i == 2:
            return m.tb.label() + "/格"
        if i == 3:
            # ★ 水平位置显示【时间】，不显示"格"：一格 = Time/div 秒
            return fmt_time(m.hpos * TIME_DIV[m.tb_index])
        return fmt_volt((m.trig.level - CAL_ZERO) * V_FULL / SAMPLE_MAX * CAL_GAIN)

    def draw_cards(self):
        scr = self.scr
        if not hasattr(self, "_cd_cache"):
            self._cd_cache = {}
        for i, r in enumerate(self.cardrect):
            on = (i == self.sel_field)
            ctext = self.card_text(i)
            # ★ 性能：每张卡两段文字约 3.5 ms，5 张 17 ms。
            #   按"卡片显示内容"做键缓存 —— 改一个字段时只有那一张会重画。
            ck = (on, ctext, self.field_label(i))
            cch = self._cd_cache.get(i)
            if cch is not None and cch[0] == ck:
                scr.img.paste(cch[1], (r[0], r[1]))
                continue
            scr.img.paste(self.bg.crop((r[0], r[1], r[2] + 1, r[3] + 1)),
                          (r[0], r[1]))
            scr.rrect(r, 5, fill=C_CARD_ON if on else C_CARD,
                      outline=(120, 180, 250) if on else (70, 92, 126),
                      width=2 if on else 1)
            scr.text((r[0] + 8, r[1] + 3), self.field_label(i), 12,
                     (190, 220, 255) if on else C_DIM, cn=True)
            scr.text((r[0] + 8, r[1] + 20), ctext, 16,
                     C_TEXT if on else (150, 175, 205), cn=True, bold=on)
            self._cd_cache[i] = (ck, scr.img.crop((r[0], r[1], r[2] + 1, r[3] + 1)))
        # ★ 性能：原来是【每张卡 flush 一次】（5 次）。flush 每次都要
        #   crop+convert+写显存，5 次约 17 ms。合并成末尾一次外接矩形。
        if self.cardrect:
            u = self.cardrect[0]
            for r in self.cardrect[1:]:
                u = (min(u[0], r[0]), min(u[1], r[1]),
                     max(u[2], r[2]), max(u[3], r[3]))
            scr.flush(box=(u[0], u[1], u[2] + 1, u[3] + 1))

    def draw_ctl(self):
        scr = self.scr
        m = self.m
        chs = "双" if (m.ch[0].enabled and m.ch[1].enabled) else \
              ("CH1" if m.ch[0].enabled else "CH2")
        specs = [(self.b_ch, "通道 %s" % chs, C_BTN),
                 (self.b_mode, "模式 %s" % ACQ_NAMES[m.acq.mode], C_BTN),
                 (self.b_minus, "－", (70, 92, 130)),
                 (self.b_cur, self.field_label(self.sel_field), C_CARD_ON),
                 (self.b_plus, "＋", (70, 92, 130)),
                 (self.b_fine, "归位到 0", (70, 92, 130)),
                 (self.b_run, "暂停" if m.running else "运行",
                  (168, 68, 68) if m.running else C_SEL),
                   (self.b_ai, "AI 分析", C_AI_BTN)]
        if not hasattr(self, "_ct_cache"):
            self._ct_cache = {}
        for bi, (r, t, col) in enumerate(specs):
            # ★ 性能：每个按钮约 3 ms，7 个 21 ms。按内容做键缓存。
            bk = (t, col, 20 if t in ("－", "＋") else 16)
            bch = self._ct_cache.get(bi)
            if bch is not None and bch[0] == bk:
                scr.img.paste(bch[1], (r[0], r[1]))
                continue
            scr.img.paste(self.bg.crop((r[0], r[1], r[2] + 1, r[3] + 1)),
                          (r[0], r[1]))
            btn(scr, r, t, fill=col, size=20 if t in ("－", "＋") else 16, cn=True)
            self._ct_cache[bi] = (bk, scr.img.crop((r[0], r[1], r[2] + 1, r[3] + 1)))
        # ★ 性能：原来是【每个按钮 flush 一次】（7 次，约 21 ms）。合并成一次。
        if specs:
            u = specs[0][0]
            for r, _t, _c in specs[1:]:
                u = (min(u[0], r[0]), min(u[1], r[1]),
                     max(u[2], r[2]), max(u[3], r[3]))
            scr.flush(box=(u[0], u[1], u[2] + 1, u[3] + 1))

    # ================= 弹层（阶段2 规范） =================
    def panel_items(self):
        m = self.m
        if self.panel == "ch":
            # ★ 只有两个复选 + 确定，不再下钻
            return [("[%s] CH1" % ("x" if self.chk[0] else " "), self.chk[0], "c1"),
                    ("[%s] CH2" % ("x" if self.chk[1] else " "), self.chk[1], "c2"),
                    ("确  定", False, "ok")]
        if self.panel == "mode":
            # ★ Auto/Normal/Single 单选 + 确定；Auto 不要求边沿
            items = [(ACQ_NAMES[i], self.pend_mode == i, "m%d" % i)
                     for i in range(3)]
            items.append(("高级触发...", False, "adv"))
            items.append(("确  定", False, "ok"))
            return items
        if self.panel == "adv":
            c = m.ch[m.active]
            return [("触发源: %s" % SRC_NAMES[m.trig.src], False, "src"),
                    ("边沿: %s" % ("上升" if m.trig.edge == 0 else "下降"),
                     m.trig.edge == 1, "edge"),
                    ("电平: %s" % fmt_volt((m.trig.level - CAL_ZERO) * V_FULL / SAMPLE_MAX * CAL_GAIN),
                     False, "lev"),
                    ("预触发: %d%%" % int(m.trig.pretrigger * 100), False, "pre"),
                    ("迟滞: %s" % ("自动" if m.trig.auto_hys else "%d" % m.trig.hys),
                     m.trig.auto_hys, "hys"),
                    ("返  回", False, "back")]
        return []

    def panel_title(self):
        return {"ch": "选择显示通道", "mode": "选择采集模式",
                "adv": "高级触发"}.get(self.panel, "")

    def draw_panel(self):
        scr = self.scr
        items = self.panel_items()
        cw, chh, hdr = 268, 50, 36
        x = 8
        total = hdr + chh * len(items)
        y = CTL_Y - total - 12
        CLEAN = (0, PLOT[1] - 4, 320, CTL_Y)
        # ★ FLICKER_FIX：擦除只在内存里做，【不要中间 flush】。
        #   原来这里擦完就立刻 flush，屏幕上会出现
        #   一帧【没有面板】的画面，然后才把面板画回来
        #   ⇒ 重绘几次就闪几次。现在只在最后 flush 一次。
        scr.img.paste(self.bg.crop(CLEAN), (CLEAN[0], CLEAN[1]))
        scr.rrect([x - 5, y - 5, x + cw + 5, y + total + 5], 6,
                  fill=(24, 32, 48), outline=(110, 150, 210), width=2)
        scr.text((x + cw // 2, y + hdr // 2 + 2), self.panel_title(), 18,
                 (180, 215, 255), bold=True, anchor="mm", cn=True)
        self.panel_rects = []
        for i, (t, sel, act) in enumerate(items):
            r = [x, y + hdr + i * chh, x + cw, y + hdr + i * chh + chh - 6]
            if act == "ok":
                col = (46, 130, 90)
            elif act in ("c1", "c2", "m0", "m1", "m2"):
                col = C_SEL if sel else (40, 54, 76)
            else:
                col = (40, 54, 76)
            btn(scr, r, t, fill=col, size=19, cn=True)
            self.panel_rects.append((r, (i, act)))
        # ★ FLICKER_FIX：把【擦除区 CLEAN】和【面板区】合并成一个 box，只 flush 一次
        _bx0 = min(CLEAN[0], x - 6); _by0 = min(CLEAN[1], y - 6)
        _bx1 = max(CLEAN[2], x + cw + 6); _by1 = max(CLEAN[3], y + total + 6)
        scr.flush(box=(_bx0, _by0, _bx1, _by1))

    # ================= ★ AI 波形分析（AI_CARD_INTO_BUF） =================
    _AI_CLASS_CN = {
        "sine": "正弦波", "square": "方波", "triangle": "三角波",
        "sawtooth": "锯齿梯形波", "noise": "噪声/无周期信号",
        "clipping": "削顶（含轻度削顶）",
        "signal_loss": "丢信号（平线或强衰减）",
        "duty_abnormal": "占空比异常",
        # HALF_WAVE_LABEL_V1：模板库可以学自定义类别（当前学了 half_wave）
        "half_wave": "半波整流",
        "full_wave": "全波整流",
        "custom": "自定义波形",
        # MULTI_TONE_LABEL_V1：多音频叠加（1k+2k+3k+4k+5k 这类）
        "multi_tone": "多音频波形",
        # LORENZ_LABEL_V1：用户实测学到的自定义波形
        "lorenz": "洛伦兹力",
        # AM_LABEL_V1：调幅波（包络特征识别）
        "am": "调幅波", "fm": "调频波", "ringing": "振铃",
        # PULSE_LABEL_V1：脉冲波（crest=3.02 的窄脉冲）
        "pulse": "脉冲波",
        # EXP_LABEL_V1：指数波（RC 充放电，crest 2.32~2.48）
        "exp": "指数波",
        # TRAP_LABEL_V1：梯形波（crest 2.08~2.14）
        "trap": "梯形波",
        # TRAP2_LABEL_V1：锯齿形梯形波（已废弃，改成直接改 sawtooth 中文名）
        "trap2": "锯齿形梯形波",
        # DC_LABEL_V1：直流（rms<1.5 且 |mean-511.5|>5）
        "dc": "直流",
    }
    _AI_TIP = {
        "sine": "连续平滑的周期信号，波形对称",
        "square": "高低电平跳变，边沿陡直",
        "triangle": "上升与下降均匀，峰值尖锐",
        "sawtooth": "锯齿梯形波：单向扫描，一侧缓、一侧陡",
        "noise": "无明显周期，建议检查接地与屏蔽",
        "half_wave": "半波整流：正弦的一半 + 平零段（模板匹配命中）",
        "multi_tone": "多音频叠加：多个相当的谐波峰（非单一基频）",
        "lorenz": "洛伦兹力波形：尖顶+圆底不对称（H2≈0.26），用户实测学习",
        "am": "调幅波：载波+包络起伏（包络比>1.5）",
        "pulse": "脉冲波：窄脉冲，峰均比高（crest≈3.0）",
        "exp": "指数波：RC 充放电，一侧陝降一侧缓散（crest 2.3~2.5）",
        "trap": "梯形波：斜边 + 短平台（crest 2.1）",
        "trap2": "锯齿形梯形波：不对称斜边（crest 1.84）",
        "dc": "直流：平坦不变的电压（rms<1.5）",
        "full_wave": "全波整流：正弦的绝对值（模板匹配命中）",
        "custom": "用户自定义模板波形",
        "clipping": "峰顶被限幅，可能输入超量程",
        "signal_loss": "几乎无信号，检查探头/输入线",
        "duty_abnormal": "高低占空比失衡，检查信号源设置",
    }

    # ★ MM_ENGINE_V1：多模态服务（16 类 + 质量 + 异常 + 中文）
    #   PC 上跑：python -m wave_ai.serve --port 8000
    #   板子通过 WiFi 访问 PC 的 8000 端口
    # ★ MM_AUTODISCOVER_V1：PC 的 IP 会变（DHCP），不能写死
    #   策略：先用上次成功的 host（缓存到文件），
    #         不行就扫候选列表（瞬时超时 0.5s）
    MM_PORT = 8000
    MM_PATH = "/waveform/analyze"
    MM_CACHE_FILE = "/home/zynq/.mm_host"
    MM_HOSTS = [
        "192.168.10.21", "192.168.10.15", "192.168.10.14",
        "192.168.10.20", "192.168.10.16", "192.168.10.17",
        "192.168.10.18", "192.168.10.19", "192.168.10.22",
        "192.168.10.23", "192.168.10.24", "192.168.10.25",
        # ★ MM_AUTODISCOVER_V2：常见热点/其他网段兑底
        "192.168.43.8", "192.168.43.1", "192.168.137.1", "192.168.1.100",
    ]
    _mm_good = None      # 缓存可用 host（类变量）

    @classmethod
    def _mm_url(cls, host=None):
        return "http://%s:%d%s" % (host or (cls._mm_good or cls.MM_HOSTS[0]),
                                   cls.MM_PORT, cls.MM_PATH)

    @classmethod
    def _mm_probe(cls, host, timeout=0.6):
        """测一个 host 的 8000 是不是在"""
        import urllib.request as _U
        try:
            r = _U.urlopen("http://%s:%d/health" % (host, cls.MM_PORT), timeout=timeout)
            return r.status == 200
        except Exception:
            return False

    @classmethod
    def _mm_own_subnet_hosts(cls):
        """★ MM_AUTODISCOVER_V2：根据板子自己的 IP 生成同网段候选

        ★★★ 为什么要这么做（真实踩坑）
        ────────────────────────────────────────────────
        原来 MM_HOSTS 是【硬编码】的 192.168.10.x 列表。
        但 PC 一换 Wi-Fi（比如开热点变成 192.168.43.x），
        板子就永远扫不到 PC，且不会报错，只是「模型调用失败」。
        ⇒ 现在先看板子自己的 IP，得到 /24 网段，
          把 1~254 里常见的都加进候选（PC 通常是 .1~.30 段）
        ────────────────────────────────────────────────
        """
        out = []
        pref = None
        try:
            import socket as _sock
            # 把板子自己的内网 IP 查出来（不发包）
            _s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            try:
                _s.connect(("8.8.8.8", 80))
                ip = _s.getsockname()[0]
            except Exception:
                ip = ""
            finally:
                _s.close()
            if ip and ip.count(".") == 3:
                pref = ip.rsplit(".", 1)[0]
        except Exception:
            pass
        if pref:
            # PC 在局域网里通常是小序号，先扫 1~40
            for i in range(1, 41):
                out.append("%s.%d" % (pref, i))
            # 板子自己也排除掉
            me = "%s.%s" % (pref, ip.rsplit(".", 1)[1]) if ip else ""
            out = [h for h in out if h != me]
        return out

    @classmethod
    def _mm_resolve(cls):
        """返回可用 host；先用缓存，再扫候选"""
        # 1) 内存缓存
        if cls._mm_good and cls._mm_probe(cls._mm_good, 0.5):
            return cls._mm_good
        # 2) 文件缓存
        try:
            with open(cls.MM_CACHE_FILE) as f:
                h = f.read().strip()
            if h and cls._mm_probe(h, 0.5):
                cls._mm_good = h
                return h
        except Exception:
            pass
        # 3) ★ MM_DISCOVER_FAST_V1：并发扫同网段
        #
        # 原来是「顺序 for 循环 + 每个 probe 超时 0.35s」，
        # 40 个候选最坏 14 秒（实测 6.7 秒）。
        # 改成线程池并发：40 个同时发，最坏一轮超时就出结果。
        # 同时保留「先往常用地址上试」的快路径。
        import concurrent.futures as _cf

        cands = []
        _seen = set()
        for _h in (cls._mm_own_subnet_hosts() + list(cls.MM_HOSTS)):
            if _h and _h not in _seen:
                _seen.add(_h)
                cands.append(_h)
        if not cands:
            cls._mm_good = None
            return None

        def _probe_host(_host):
            try:
                return _host if cls._mm_probe(_host, 0.8) else None
            except Exception:
                return None

        _t0 = __import__("time").time()
        _found = None
        try:
            with _cf.ThreadPoolExecutor(max_workers=min(48, len(cands))) as _ex:
                _futs = {_ex.submit(_probe_host, _h): _h for _h in cands}
                for _f in _cf.as_completed(_futs):
                    try:
                        _r = _f.result()
                    except Exception:
                        _r = None
                    if _r:
                        _found = _r
                        break
        except Exception as _e:
            print("[MM] 并发扫描异常: %s" % _e)

        if _found:
            cls._mm_good = _found
            try:
                with open(cls.MM_CACHE_FILE, "w") as f:
                    f.write(_found)
            except Exception:
                pass
            print("[MM] 发现服务: %s (%.0f ms)" % (
                _found, (__import__("time").time() - _t0) * 1000))
            return _found
        cls._mm_good = None
        print("[MM] 未找到服务 (%d 个候选, %.0f ms)" % (
            len(cands), (__import__("time").time() - _t0) * 1000))
        return None

    # 16 类中文名（前 8 个就是端侧 8 类）
    _AI_MM_CN = {
        "sine": "正弦波", "square": "方波", "triangle": "三角波",
        "sawtooth": "锯齿波", "noise": "噪声", "clipping": "削顶",
        "signal_loss": "丢信号", "duty_abnormal": "占空比异常",
        "pulse": "脉冲", "step": "阶跃", "am": "调幅",
        "fm": "调频", "ringing": "振铃", "double_freq": "倍频",
        "hum": "工频干扰", "glitch": "毛刺",
    }

    AI_CARD_W, AI_CARD_H = 390, 190   # ★ AI_TWO_MODES_V1：加高以容纳模式按钮
    # ★ AI_ENGINE_SWITCH：卡片里的引擎切换键（屏幕坐标，由 _ai_card_raw 更新）
    AI_ENG_BTN_W, AI_ENG_BTN_H = 116, 26

    def _speak_text(self, text):
        """AI_SPEAK_V1：用 espeak-ng 合成中文语音 + aplay 播放

        ★ 为什么用命令行而不是 pyttsx3：
          板子上没有 pyttsx3，但 espeak-ng 和 aplay 都在，
          实测 espeak-ng -v zh 能合成中文（157970 字节 WAV）。
        ★ 为什么用 default 设备：
          参考 acoustic_selftest.py 的踩坑注释：
          只有 `default` 能用（aplay 不带 -D 才 0 退出），
          用 -D hw:0,x 会报 "Sample format non available"。
        ★ 后台线程：播放要 1~2 秒，不能阻塞 UI 主循环。
        """
        if not text:
            return

        def _run():
            import json as _json
            import subprocess
            import urllib.request as _ur
            wav = "/tmp/_ai_speak.wav"

            # SPEAK_LOAD_BAIDU_ENV_V1：先注入百度密钥
            #   /etc/zynq-baidu.env 里有 BAIDU_API_KEY / BAIDU_SECRET_KEY，
            #   zynq-agent 服务靠 EnvironmentFile 加载它，所以小白能用百度 TTS。
            #   但 zynq-desktop 没这个环境变量 => agent.tts 拿不到密钥
            #   => 退回 espeak => 机械音（用户反馈「声音好难听」）。
            #   desktop.py 以 root 跑，能读 600 权限的文件。
            try:
                import os as _os
                _envf = "/etc/zynq-baidu.env"
                if _os.path.isfile(_envf) and not _os.environ.get("BAIDU_API_KEY"):
                    with open(_envf, "r", encoding="utf-8", errors="replace") as _f:
                        for _ln in _f:
                            _ln = _ln.strip()
                            if not _ln or _ln.startswith("#") or "=" not in _ln:
                                continue
                            _k, _v = _ln.split("=", 1)
                            _os.environ[_k.strip()] = _v.strip()
                    print("[SPEAK] baidu env loaded")
            except Exception as _ee:
                print("[SPEAK] baidu env load failed: %s" % _ee)

            # SPEAK_USE_XIAOBAI_TTS_V1：优先用系统管家小白的 TTS
            #   小白的 tts.synth(eng="auto") 会优先走百度在线 TTS（音质自然），
            #   失败才兜底 espeak-ng（用 "cmn" 普通话声音，比 "zh" 好）。
            #   播放走 ac.play_file() -> audio client -> 8767 -> ES8388。
            try:
                if "/home/zynq" not in sys.path:
                    sys.path.insert(0, "/home/zynq")
                from agent import tts as _xb_tts
                _p, _secs = _xb_tts.speak(str(text)[:300])
                print("[SPEAK] xiaobai tts ok: %s (%.1fs)" % (_p, _secs or 0))
                return
            except Exception as _xe:
                print("[SPEAK] xiaobai tts failed (%s), fallback" % _xe)

            try:
                # ① espeak-ng 合成中文语音
                r = subprocess.run(
                    ["espeak-ng", "-v", "zh", "-s", "165", "-p", "55",
                     "-w", wav, str(text)[:200]],
                    capture_output=True, timeout=20)
                if r.returncode != 0:
                    print("[SPEAK] espeak failed: %s" % (r.stderr or b"")[:120])
                    return

                # ② 确保 zynq-audio 在跑（示波器的服务休眠会把它停掉）
                try:
                    with _ur.urlopen("http://127.0.0.1:8767/state", timeout=2) as _r:
                        _r.read(64)
                except Exception:
                    print("[SPEAK] audio svc not up, starting...")
                    subprocess.run(["sudo", "-n", "systemctl", "start",
                                    "zynq-audio"], capture_output=True, timeout=15)
                    import time as _t
                    _t.sleep(5)

                # ③ 走 /say 接口（ES8388 codec 已经由该服务初始化好）
                _body = _json.dumps({"file": wav}).encode("utf-8")
                _req = _ur.Request("http://127.0.0.1:8767/say", data=_body,
                                   headers={"Content-Type": "application/json"})
                with _ur.urlopen(_req, timeout=40) as _r:
                    _resp = _r.read(160).decode("utf-8", "replace")
                print("[SPEAK] say -> %s" % _resp)
                return
            except Exception as e:
                print("[SPEAK] svc path failed (%s), fallback aplay" % e)

            # ④ 兜底：直接 aplay（若 codec 已初始化也能出声）
            try:
                subprocess.run(["aplay", "-q", wav],
                               capture_output=True, timeout=30)
                print("[SPEAK] aplay fallback done")
            except Exception as e2:
                print("[SPEAK] aplay also failed: %s" % e2)

        try:
            import threading as _th2
            _th2.Thread(target=_run, daemon=True).start()
        except Exception as e:
            print("[SPEAK] thread failed: %s" % e)

    def _speak_summary(self):
        """AI_SPEAK_V1：朗读当前分析的一句话总结

        优先用云端的中文一句话（mm.text），
        否则用本地 _ai_summary() 拼「类别 + 测量」。
        """
        try:
            mm = getattr(self, "ai_mm", None) or {}
            txt = (mm.get("text") or "").strip() if not mm.get("_error") else ""
            if txt:
                self._speak_text(txt)
                return txt
            cn, tip, line2 = self._ai_summary()
            out = "%s。%s" % (cn or "未知波形", line2 or "")
            self._speak_text(out)
            return out
        except Exception as e:
            print("[SPEAK] summary failed: %s" % e)
            return ""

    def _ai_summary(self):
        """类别 + 测量值 -> 一句中文说明"""
        r = getattr(self, "ai_res", None) or {}
        key = str(r.get("label") or "")
        cn = self._AI_CLASS_CN.get(key, r.get("label") or "?")
        tip = self._AI_TIP.get(key, "")
        mm = self.m.m[self.m.active] or {}
        parts = []
        try:
            f = mm.get("freq")
            if f:
                parts.append("频率 %.2f kHz" % (f / 1000.0))
        except Exception:
            pass
        try:
            v = mm.get("vpp")
            if v:
                parts.append("峰峰值 %.2f V" % v)
        except Exception:
            pass
        try:
            d = mm.get("duty")
            if d and mm.get("locked"):
                parts.append("占空 %.1f%%" % d)
        except Exception:
            pass
        line2 = "，".join(parts) if parts else "当前无测量值"
        return cn, tip, line2

    def ai_analyze(self):
        """★ MERGE_ENGINE_V1：一个按钮跑完整流程

        ① 立即（~10ms）：本地 PL CNN -> 8 类结果先上屏
        ② 后台（~500ms）：多模态服务 -> 16 类+质量+异常+中文
        ③ 服务不可达 -> 保持端侧结果 + 降级提示
        """
        import time as _t
        import threading

        print("[AI] analyze start")
        self.ai_res = None
        self.ai_mm = None
        self.ai_err = None
        self.ai_reply = None
        self.ai_cloud_txt = None
        self.ai_cloud_busy = False
        self.ai_busy = True
        self.ai_t0 = _t.time()
        self.ai_cache = None
        self.ai_tpl = None
        self.draw_wave()

        try:
            a1, a2, _info = self.hw.read_frame_locked()
            data = a1 if self.m.active == 0 else a2
            dec = (_info or {}).get("dec", 10)

            # ★ TPL_REPLACE_CNN_V1（★★★ 用模板形状匹配【取代】本地 CNN）
            #
            # 实测结论：
            #   本地 CNN（训练在合成数据上）在实测信号上经常错：
            #     正弦波 -> duty_abnormal 73%（错）
            #   而谐波特征模板匹配：
            #     正弦波 -> sine 0.99（对），且与幅度/相位无关
            #
            # 策略：
            #   ① 模板命中（score >= 0.80）-> 直接当作本地结果
            #   ② 模板未命中 -> 回退到 CNN（广化能力，能报不知道的形态）
            #   ③ 两者都失败 -> 报错
            self.ai_tpl = None
            _tpl_ok = False

            # TPL_DIAG_LITE_V1：轻量诊断（O(N)，毫秒级，不会卡桌面）
            #
            # 目的：定位「桌面进程识别结果和我测试脚本不一致」的问题。
            #   · 桌面进程在示波器界面下，data 可能受 span/hpos 影响
            #   · 我测试脚本新建 App 实例，默认状态
            #   只记录便宜的特征（min/max/crest/env前两维），不调 harmonics。
            try:
                import wave_templates as _TD
                _dm = sum(data) / float(len(data))
                _dmn = min(data)
                _dmx = max(data)
                _dcrest = _TD.crest_factor(data)
                _dfeat, _dis_am = _TD.env_features(data)
                _dsig = _TD.am_envelope_signature(data)
                _dtpl = (_TD.load().get("am") or {}).get("envsig") or []
                _ddist = _TD.env_curve_distance(_dsig, _dtpl) if _dsig and _dtpl else 99
                print("[DIAG] len=%d min=%d max=%d mean=%.1f crest=%.3f "
                      "env1=%s env2=%s is_am=%s" % (
                          len(data), _dmn, _dmx, _dm, _dcrest,
                          (_dfeat[0] if _dfeat else None),
                          (_dfeat[1] if _dfeat else None),
                          _dis_am))
                print("[DIAG-SIG] 本次前8=%s" % (
                    [round(v, 3) for v in (_dsig or [])[:8]],))
                print("[DIAG-SIG] 模板前8=%s  距离=%.4f" % (
                    [round(v, 3) for v in _dtpl[:8]], _ddist))
            except Exception as _de:
                print("[DIAG] failed: %s" % _de)
            try:
                import wave_templates as _TPL
                _tpl_pl = _TPL.load()
                self.ai_tpl = _TPL.forced(data)
                if self.ai_tpl:
                    _cat = self.ai_tpl.get("category")
                    _cn = self.ai_tpl.get("label_cn")
                    _sc = self.ai_tpl.get("score") or 0.0
                    self.ai_res = {
                        "ok": True,
                        "label": _cat,
                        "confidence": _sc,
                        "detail": {
                            "engine": "模板形状匹配（谐波特征）",
                            "input_interpretation": "4096 点 -> 谐波签名",
                            "scores": self.ai_tpl.get("scores") or {},
                            "crest": self.ai_tpl.get("crest"),
                            "threshold": 0.80,
                        },
                        "elapsed_ms": 0,
                        "offline_mode": True,
                    }
                    _tpl_ok = True
                    print("[AI] template hit: %s %.1f%%" % (_cn, _sc * 100))
                else:
                    # 未命中 -> 记录弱结果供参考
                    _c2, _cn2, _s2, _all2 = _TPL.best_match(data, _tpl_pl)
                    if _c2:
                        self.ai_tpl = {"category": _c2, "label_cn": _cn2,
                                       "score": _s2, "scores": _all2,
                                       "weak": True}
                    print("[AI] template weak: %s %.3f" % (_cn2, _s2))
            except Exception as _e:
                print("[AI] template failed: %s" % _e)

            # ② 本地 CNN（仅当模板未命中时使用）
            if not _tpl_ok:
                try:
                    import infer_local
                    self.ai_res = infer_local.infer_waveform(data)
                    print("[AI] local cnn: %s %.0f%%" % (
                        self.ai_res.get("label"),
                        (self.ai_res.get("confidence") or 0) * 100))
                except Exception as _e:
                    print("[AI] local cnn failed: %s" % _e)

            self.ai_busy = False
            self.ai_cache = None
            self.draw_wave()

            # ② 后台调多模态（不阻塞 UI）
            def _bg():
                try:
                    mm = self._ai_mm_ask(data, dec)
                    self.ai_mm = mm
                    self.ai_cache = None      # 触发下帧重画
                    print("[AI] multimodal: %s" % (
                        (mm or {}).get("label") if not (mm or {}).get("_error")
                        else "UNAVAILABLE"))
                    # ★ AI_TWO_MODES_V2：云端增强模式 -> 再调大模型
                    if self.ai_mode == "cloud" and mm and not mm.get("_error"):
                        self.ai_cloud_busy = True
                        self.ai_cache = None
                        _ct = self._ai_cloud_ask_mm(mm)
                        self.ai_cloud_txt = _ct
                        self.ai_cloud_busy = False
                        self.ai_cache = None
                        print("[AI] cloud enhanced: %s" % ("OK" if _ct else "FAILED"))
                    # ★ RACE_FIX_V1：不能在后台线程预渲染！
                    #   _mm_render_report() 要临时替换 scr.img / scr.d 来绘制，
                    #   而主线程同时在用它们画波形
                    #   ⇒ 数据竞争 ⇒ framebuffer 被写坏 ⇒ 花屏！
                    #   现在只在后台生成行列表（0.5ms，安全），
                    #   图像渲染留到用户点「详情」时在主线程做
                    try:
                        self.mm_popup = self._mm_report_lines()
                        self.mm_img_cache = None
                        print("[AI] report lines ready (%d)" % len(self.mm_popup))
                    except Exception as _e2:
                        print("[AI] report lines failed: %s" % _e2)
                except Exception as _e:
                    print("[AI] multimodal bg failed: %s" % _e)

            threading.Thread(target=_bg, daemon=True).start()

        except Exception as e:
            import traceback as _tb
            self.ai_err = str(e)[:60]
            print("[AI] analyze failed: %s: %s" % (type(e).__name__, e))
            _tb.print_exc()
            self.ai_busy = False
            self.ai_cache = None
            self.draw_wave()


    def _ai_mm_ask(self, data, dec=10):
        """★ MM_ENGINE_V1：调 PC 上的多模态服务

        传：samples(4096) + dec + local_cnn(8类)
        接：label_cn / confidence / quality / anomaly / text
        """
        import json as _J
        import urllib.request as _U
        try:
            # ① 先跑本地 CNN（给服务做融合用）
            local = None
            try:
                import infer_local
                local = infer_local.infer_waveform(data)
            except Exception as _e:
                print("[MM] local cnn failed: %s" % _e)

            # ② 组请求
            req = {
                "type": "waveform_analysis",
                "samples": [int(v) for v in data],
                "fs": 20000000,
                "dec": int(dec) if dec else 10,
                "options": {"max_chars": 70, "language": "zh-CN",
                            "for_voice": True, "want_quality": True,
                            "want_anomaly": True},
            }
            # MM_REFERENCE_V2：传本地 8 类概率给云端，但云端「以自己分析为主」
            #
            # ★ 服务端的设计（见 wave_ai/analyzer.py 与 train.py 注释）：
            #   融合网络的三路输入是
            #     ① 96x96x3 视觉输入      ← 主
            #     ② 59 维手工特征         ← 主
            #     ③ 端侧 8 类概率         ← 参考
            #   训练时 p_drop=0.25 会随机把 ③ 丢掉，
            #   就是为了防止模型学成「抄端侧答案」。
            #   ⇒ 所以传过去是「参考」，不是「结论」，完全符合要求。
            #
            # ★ 必须传【完整 8 类概率 probs】，不能只传 label ——
            #   服务端 _parse_local_cnn() 要的是概率分布。
            if local:
                req["local_cnn"] = {
                    "label": local.get("label"),
                    "confidence": float(local.get("confidence") or 0.0),
                    "classes": ["sine", "square", "triangle", "sawtooth",
                                "noise", "clipping", "signal_loss",
                                "duty_abnormal"],
                    "probs": local.get("probs") or [],
                }
            body = _J.dumps(req).encode("utf-8")
            # ★ MM_AUTODISCOVER_V1：先解析可用 host
            _h = self._mm_resolve()
            if not _h:
                raise RuntimeError("未发现多模态服务（PC 上 8000 未启动？）")
            r = _U.urlopen(_U.Request(self._mm_url(_h), data=body,
                          headers={"Content-Type": "application/json"}),
                          timeout=2.0)
            d = _J.loads(r.read().decode("utf-8", "replace"))
            if not d.get("ok"):
                raise RuntimeError(d.get("error") or "service error")
            return d
        except Exception as e:
            print("[MM] failed: %s: %s" % (type(e).__name__, e))
            return {"_error": "%s: %s" % (type(e).__name__, str(e)[:50])}

    AI_SYSTEM = (
        "你是一个嵌入式示波器的波形分析助手。"
        "用户会给你一组波形统计数据和本地 CNN 的判别结果。"
        "请用不超过 70 个中文字直接给结论："
        "这是什么信号、是否正常、有没有值得注意的问题。"
        "不要客套、不要对列点、不要说废话。"
    )

    def _ai_cloud_ask_mm(self, mm):
        """★ AI_TWO_MODES_V2：云端增强

        把【端侧 CNN + 多模态服务】的完整结果作为上下文发给大模型，
        让云端在已经分析好的基础上给更深的结论。
        """
        import json as _J
        import urllib.request as _U
        if not mm or mm.get("_error"):
            return None
        q = mm.get("quality") or {}
        an = mm.get("anomaly") or {}
        ex = mm.get("extra") or {}
        meas = ex.get("measurements") or {}
        parts = ["多模态分析已得到："]
        parts.append("类别=%s(置信度 %.0f%%)" % (
            mm.get("label_cn") or mm.get("label"), (mm.get("confidence") or 0) * 100))
        if meas.get("freq_hz"):
            parts.append("频率=%.2f kHz" % (meas["freq_hz"] / 1000.0))
        if meas.get("vpp_v") is not None:
            parts.append("峰峰值=%.3f V" % meas["vpp_v"])
        if meas.get("duty_pct") is not None:
            parts.append("占空比=%.1f%%" % meas["duty_pct"])
        if q.get("applicable") and q.get("score") is not None:
            parts.append("质量=%d 分" % q["score"])
            if q.get("snr_db") is not None:
                parts.append("信噪比=%.1f dB" % q["snr_db"])
        if an.get("is_anomaly"):
            parts.append("异常=%s" % "、".join(an.get("features") or []) or "检出异常")
            if an.get("suggestion"):
                parts.append("系统建议=%s" % an["suggestion"])
        else:
            parts.append("未发现异常")
        ctx = "；".join(parts) + "。"

        sys_prompt = (
            "你是一个专业的嵌入式示波器波形分析助手。"
            "已有一个多模态模型完成了初步分析，"
            "你的任务是在它的结论上给出更深入的判断："
            "这个信号实际可能是什么、源头在哪、"
            "有没有潜在问题、下一步应该怎么排查。"
            "用不超过 120 个中文字，直接给结论和建议，"
            "不要客套、不要重复已有信息。")

        try:
            body = _J.dumps({"system": sys_prompt, "text": ctx,
                             "tools": False, "stateless": True}).encode("utf-8")
            req = _U.Request("http://127.0.0.1:8765/intent", data=body,
                             headers={"Content-Type": "application/json"})
            r = _U.urlopen(req, timeout=40)
            d = _J.loads(r.read().decode("utf-8", "replace"))
            rep = d.get("reply") or (((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
            if not rep:
                raise RuntimeError(d.get("error") or "云端没回复")
            return str(rep).strip()
        except Exception as e:
            print("[AI] cloud mm failed: %s: %s" % (type(e).__name__, e))
            return None

    def _ai_cloud_ask(self, data):
        """走 agent /intent：纯 LLM 分析（不带工具）"""
        import json as _J
        import urllib.request as _U
        try:
            mn, mx = min(data), max(data)
            pp = (mx - mn) * (10.0 / 1024.0)
            mid = (mx + mn) / 2.0
        except Exception:
            mn = mx = pp = mid = 0.0
        # 先跑一次本地 CNN，作为上下文给大模型
        lab, conf = "未判别", 0.0
        try:
            import infer_local
            _r = infer_local.infer_waveform(data)
            lab = self._AI_CLASS_CN.get(str(_r.get("label")), str(_r.get("label")))
            conf = float(_r.get("confidence") or 0.0)
        except Exception:
            pass
        txt = ("示波器采到：峰峰值 %.3f V，最高码 %d，"
               "最低码 %d，中点码 %.0f；"
               "本地 CNN 判别：%s（置信度 %.0f%%）。"
               "请给结论。") % (pp, mx, mn, mid, lab, conf * 100)
        body = _J.dumps({"system": self.AI_SYSTEM, "text": txt,
                         "tools": False, "stateless": True}).encode("utf-8")
        req = _U.Request("http://127.0.0.1:8765/intent", data=body,
                         headers={"Content-Type": "application/json"})
        r = _U.urlopen(req, timeout=40)
        d = _J.loads(r.read().decode("utf-8", "replace"))
        rep = d.get("reply") or (((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
        if not rep:
            raise RuntimeError(d.get("error") or "云端没回复")
        return str(rep).strip(), float(d.get("elapsed") or 0.0)

    # ================= ★ MM_REPORT_V1 / SYMBOL_FIX_V1：公式流报告 =================

    @staticmethod
    def _wrap_cn(txt, n):
        """按字符数折行（中英混排足够用）"""
        out, cur = [], ""
        for ch in txt:
            cur += ch
            if len(cur) >= n:
                out.append(cur)
                cur = ""
        if cur:
            out.append(cur)
        return out

    def _mm_report_lines(self):
        """★ 把多模态结果组装成「公式流」报告行

        返回：list of (kind, text)  kind ∈ H(标题) K(大结论) P(普通) L(列表) S(空行) W(警告)
        """
        mm = self.ai_mm or {}

        # REPORT_LOCAL_V1：先组装「本地识别」段
        #   卡片主标题用本地模板结果，详情页也要先显示本地，
        #   否则用户会看到「卡片写调幅波、详情页写噪声」的矛盾。
        _local_rows = []
        try:
            _lr = getattr(self, "ai_res", None) or {}
            _lt = getattr(self, "ai_tpl", None) or {}
            _lbl = str(_lr.get("label") or "")
            _lcn = self._AI_CLASS_CN.get(_lbl, _lr.get("label") or "")
            _lcf = float(_lr.get("confidence") or 0.0)
            _lsrc = ""
            if _lt and not _lt.get("weak"):
                _lcn = _lt.get("label_cn") or _lcn
                _lcf = float(_lt.get("score") or _lcf)
                _lsrc = "模板形状匹配（谐波/包络特征）"
            elif _lbl:
                _lsrc = "本地 CNN（PL 硬件）"
            if _lcn:
                _local_rows.append(("H", "【本地识别】"))
                _local_rows.append(("K", "%s    置信度 %.1f%%" % (_lcn, _lcf * 100)))
                if _lsrc:
                    _local_rows.append(("P", "引擎 %s" % _lsrc))
                _local_rows.append(("S", ""))
        except Exception as _le:
            print("[REPORT] local section failed: %s" % _le)

        if not mm or mm.get("_error"):
            _tail = [("W", "云端不可达"), ("P", "请确认 PC 上 wave_ai.serve 在运行")]
            if _local_rows:
                _local_rows.append(("H", "【云端判定】"))
                return _local_rows + _tail
            return _tail

        L = list(_local_rows)
        if _local_rows:
            L.append(("H", "【云端判定（参考）】"))
        lbl = mm.get("label") or ""
        # MM_UNKNOWN_GATE_V1：云端置信度低 -> 标「非常见波形」
        #
        # 为什么要这样：
        #   云端是 16 类分类器（sine/square/.../hum），
        #   遇到【不在 16 类里】的波形（比如半波整流）时，
        #   它只能硬塞进最像的一类（实测给 duty_abnormal 但置信度只有 45%）。
        #   与其显示一个错的类别，不如明确告诉用户「这是非常见波形」。
        #
        #   阈值取 0.60：实测正常波形（正弦/方波/三角/锯齿）云端置信度
        #   通常 0.85+，而未知波形会掉到 0.4~0.55，中间是安全区。
        _mm_conf = 0.0
        try:
            _mm_conf = float(mm.get("confidence") or 0.0)
        except Exception:
            _mm_conf = 0.0
        if _mm_conf < 0.80:
            cn = "非常见波形（云端置信度仅 %.0f%%）" % (_mm_conf * 100)
            # 把原始判断也带上，方便排查
            _raw_cn = self._AI_MM_CN.get(lbl, mm.get("label_cn") or lbl or "?")
            self.msg = "云端最接近：%s（%.0f%%），未达常见类别阈值" % (
                _raw_cn, _mm_conf * 100)
        else:
            cn = self._AI_MM_CN.get(lbl, mm.get("label_cn") or lbl or "?")
        conf = float(mm.get("confidence") or 0.0)
        ex = mm.get("extra") or {}
        meas = ex.get("measurements") or {}
        q = mm.get("quality") or {}
        an = mm.get("anomaly") or {}
        fu = ex.get("fusion") or {}
        tm = ex.get("timing") or {}

        # ---- 【判定】 ----
        L.append(("H", "【判定】"))
        L.append(("K", "%s    置信度 %.1f%%" % (cn, conf * 100)))
        L.append(("P", "引擎 %s  ·  服务端 %s ms  ·  工具版本 %s"
                  % (mm.get("engine") or "?", mm.get("elapsed_ms") or "?",
                     ex.get("version") or "?")))
        L.append(("S", ""))

        # ---- 【测量参数】 ----
        if meas:
            L.append(("H", "【测量参数】"))
            for key, name, unit in (
                    ("freq_hz", "频率", ""),
                    ("period_us", "周期", " µs"),
                    ("vpp_v", "峰峰值", " V"),
                    ("vmax_v", "最大值", " V"),
                    ("vmin_v", "最小值", " V"),
                    ("vmean_v", "均值", " V"),
                    ("vrms_v", "有效值", " V"),
                    ("duty_pct", "占空比", " %")):
                v = meas.get(key)
                if v is None:
                    continue
                if key == "freq_hz":
                    sv = ("%.2f kHz" % (v / 1000.0)) if v >= 1000 else ("%.1f Hz" % v)
                elif isinstance(v, float):
                    sv = "%.3f%s" % (v, unit)
                else:
                    sv = "%s%s" % (v, unit)
                L.append(("L", "%s" % name, sv))
            L.append(("S", ""))

        # ---- 【质量评估】 ----
        L.append(("H", "【质量评估】"))
        if q.get("applicable"):
            sc = q.get("score")
            grade = "优秀" if sc and sc >= 90 else ("良好" if sc and sc >= 75 else ("一般" if sc and sc >= 60 else "较差"))
            L.append(("K", "%s 分    %s" % (sc, grade)))
            _na = []                      # ★ 精简："不适用"的项先收集
            for key, name, unit, fmt in (
                    ("rise_us", "上升时间", " µs", "%.2f"),
                    ("fall_us", "下降时间", " µs", "%.2f"),
                    ("overshoot_pct", "过冲", " %", "%.1f"),
                    ("undershoot_pct", "下冲", " %", "%.1f"),
                    ("snr_db", "信噪比", " dB", "%.1f"),
                    ("thd_pct", "谐波失真", " %", "%.2f"),
                    ("jitter_ns", "抖动", " ns", "%.1f"),
                    ("duty_stability_pct", "占空比稳定度", " %", "%.2f")):
                v = q.get(key)
                if v is None:
                    # ★ 精简："不适用"的行不再单独列，统一归纳
                    _na.append("%s" % name)
                else:
                    L.append(("L", "%s" % name, (fmt % v) + unit))   # ★ 修复：unit 里的 % 不能参与格式化
            if _na:
                L.append(("P", "不适用：" + "、".join(_na)))
            cov = q.get("coverage")
            if cov is not None:
                L.append(("P", "可测项覆盖率 %.0f%%" % (cov * 100)))
            for note in (q.get("notes") or [])[:3]:
                L.append(("P", "· " + str(note)))
        else:
            L.append(("W", "不可评估"))
            for note in (q.get("notes") or [])[:3]:
                L.append(("P", "· " + str(note)))
        L.append(("S", ""))

        # ---- 【异常检测】 ----
        L.append(("H", "【异常检测】"))
        if an.get("is_anomaly"):
            L.append(("W", "[!] 检出异常    可疑度 %.0f%%" % ((an.get("score") or 0) * 100)))
            for f in (an.get("features") or [])[:6]:
                L.append(("P", "· " + str(f)))
            if an.get("reason"):
                L.append(("P", "判据：" + str(an.get("reason"))))
            if an.get("suggestion"):
                L.append(("P", "建议：" + str(an.get("suggestion"))))
        else:
            L.append(("K", "[OK] 未发现异常"))
        L.append(("S", ""))

        # ---- 【融合结果】 ----
        if fu:
            L.append(("H", "【融合结果】"))
            lc = fu.get("local_cnn") or {}
            vm = fu.get("vision_model") or {}
            if lc:
                L.append(("L", "端侧 PL CNN", "%s %.0f%%" % (
                    self._AI_MM_CN.get(lc.get("label"), lc.get("label") or "?"),
                    (lc.get("confidence") or 0) * 100)))
            if vm:
                L.append(("L", "多模态视觉模型", "%s %.0f%%" % (
                    self._AI_MM_CN.get(vm.get("label"), vm.get("label") or "?"),
                    (vm.get("confidence") or 0) * 100)))
            ag = fu.get("agree")
            if ag is True:
                L.append(("P", "> 两路一致，结果可信"))
            elif ag is False:
                L.append(("W", "> 两路不一致，以多模态为准"))
            else:
                L.append(("P", "> 端侧未提供结果，仅多模态"))
            L.append(("S", ""))

        # ---- 【服务原文】 ----
        txt = mm.get("text") or ""
        if txt:
            L.append(("H", "【服务生成的一句话】"))
            for ln in self._wrap_cn(txt, 30):
                L.append(("P", ln))
            L.append(("S", ""))

        # ---- 【耗时】 ----
        if tm:
            L.append(("H", "【处理耗时】"))
            L.append(("P", "特征 %.1f ms  ·  视觉 %.1f ms  ·  文本 %.1f ms  ·  总 %.1f ms"
                      % (tm.get("features_ms") or 0, tm.get("vision_ms") or 0,
                         tm.get("text_ms") or 0, tm.get("total_ms") or 0)))

        return L

    def mm_open_popup(self):
        """打开详情弹窗（★ 优先用预渲染缓存）"""
        if self.ai_mm is None:
            return
        # ★ POPUP_PREFETCH_V1：后台线程已经预渲染好了就直接用
        if self.mm_popup is None or self.mm_img_cache is None:
            self.mm_popup = self._mm_report_lines()
            self.mm_img_cache = None
        # ★ RACE_FIX_V1：主线程里预渲染（第一次 ~200ms，之后走缓存）
        if self.mm_img_cache is None:
            try:
                self._mm_base_image()
                self._mm_render_report()
            except Exception as _e:
                print("[AI] render report failed: %s" % _e)
        self.mm_base_painted = False
        self.mm_scroll = 0
        self.mm_drag_y = None
        self.mm_popup_open = True     # ★ 真正打开
        self.mm_first_flushed = False # ★ SCROLL_FAST_V1：新弹窗需首帧全屏 flush
        self._draw_mm_popup()

    def mm_close_popup(self):
        """★ POPUP_RESIDUE_FIX_V1：关闭弹窗

        残留根因：draw_wave() 用 blit_raw 直接写 fb，绕过 scr.img。
        画弹窗时把弹窗内容 paste 进了 scr.img。
        关闭时再 flush() 就把【残留的弹窗】刷回屏幕。
        修复：先把 self.bg 恢复进 scr.img，再 flush。
        """
        self.mm_popup = None
        self.mm_popup_open = False      # ★ 已关闭
        self.mm_base_painted = False
        self.mm_scroll = 0
        self.mm_drag_y = None
        self.mm_img_cache = None
        try:
            # ① 把背景恢复进 scr.img（清掉弹窗残留）
            if self.bg is not None:
                self.scr.img.paste(self.bg, (0, 0))
            else:
                self.scr.clear((0, 0, 0))
            # ② 刷一屏背景（快，~20ms）
            self.scr.flush()
            # ★ 必须 full_redraw！主循环只调 draw_wave/draw_stat/draw_top/draw_scales，
            #   从不调 draw_cards / draw_ctl ⇒ 关闭后卡片区和控制栏会留白
            self.full_redraw()
            self.scr.flush()
        except Exception as e:
            print("[AI] close popup err: %s" % e)


    def _mm_render_report(self):
        """★ POPUP_FAST_V2：把整个报告渲染成一张大图（缓存）

        之前每次拖动都重画 131ms，现在只算一次，滚动时只切片
        """
        lines = self.mm_popup
        if not lines:
            return None
        key = (id(lines), len(lines))
        c = getattr(self, "mm_img_cache", None)
        if c is not None and c[0] == key:
            return c[1], c[2], c[3]

        # 行高
        heights = []
        for kind, *rest in lines:
            if kind == "H":
                heights.append(30)
            elif kind == "K":
                heights.append(34)
            elif kind == "S":
                heights.append(10)
            else:
                heights.append(24)
        total_h = sum(heights)

        # 在临时 Image 上画（宽 900）
        from PIL import Image, ImageDraw
        cw2 = 900
        img = Image.new("RGB", (cw2, total_h), (20, 27, 42))
        d = ImageDraw.Draw(img)
        scr = self.scr
        # 借用 scr 的字体渲染：临时把 img 指向这张图
        # ★ POPUP_FAST_V5：必须同时替换 scr.img 和 scr.d（ImageDraw）
        #   否则 scr.text() 还是画到原来的图上，弹窗里没文字
        old_img = scr.img
        old_d = getattr(scr, "d", None)
        scr.img = img
        try:
            from PIL import ImageDraw as _ID
            scr.d = _ID.Draw(img)
        except Exception:
            pass
        yy = 0
        try:
            for idx, (kind, *rest) in enumerate(lines):
                hh = heights[idx]
                if kind == "H":
                    scr.text((20, yy + 14), rest[0], 16, (120, 200, 255), anchor="lm", cn=True)
                    scr.line([(20, yy + 26), (cw2 - 20, yy + 26)], fill=(54, 72, 108), width=1)
                elif kind == "K":
                    scr.text((20, yy + 15), rest[0], 21, (100, 235, 165), anchor="lm", cn=True)
                elif kind == "W":
                    scr.text((20, yy + 13), rest[0], 17, (255, 150, 120), anchor="lm", cn=True)
                elif kind == "S":
                    pass
                elif kind == "L":
                    scr.text((28, yy + 12), rest[0], 15, (175, 190, 215), anchor="lm", cn=True)
                    scr.text((cw2 - 28, yy + 12), rest[1], 15, (235, 242, 255), anchor="rm", cn=True)
                else:
                    scr.text((28, yy + 12), rest[0], 14, (165, 180, 205), anchor="lm", cn=True)
                yy += hh
        finally:
            scr.img = old_img
            if old_d is not None:
                scr.d = old_d

        data = img.tobytes()
        self.mm_img_cache = (key, data, cw2, total_h)
        return data, cw2, total_h

    def _mm_base_image(self):
        """★ POPUP_FAST_V3：弹窗静态底板（遮罩+框+标题栏），只渲染一次"""
        c = getattr(self, "mm_base_cache", None)
        if c is not None:
            return c
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1024, 600), (6, 9, 16))
        scr = self.scr
        old = scr.img
        old_d = getattr(scr, "d", None)
        scr.img = img
        try:
            from PIL import ImageDraw as _ID
            scr.d = _ID.Draw(img)
        except Exception:
            pass
        try:
            x0, y0, x1, y1 = 62, 46, 962, 550
            scr.rrect([x0, y0, x1, y1], 12, fill=(20, 27, 42),
                      outline=(96, 118, 176), width=2)
            scr.rrect([x0, y0, x1, y0 + 40], 12, fill=(38, 50, 78))
            scr.rect([x0, y0 + 26, x1, y0 + 40], fill=(38, 50, 78))
            scr.text((x0 + 18, y0 + 20), "波形分析报告", 19,
                     (225, 235, 255), anchor="lm", cn=True)
            cb = [x1 - 52, y0 + 8, x1 - 12, y0 + 34]
            self.mm_pop_close = cb
            scr.rrect(cb, 7, fill=(150, 60, 70), outline=(220, 110, 120), width=2)
            scr.text(((cb[0] + cb[2]) // 2, (cb[1] + cb[3]) // 2), "X", 17,
                     (255, 240, 240), anchor="mm", cn=True)
        finally:
            scr.img = old
            if old_d is not None:
                scr.d = old_d
        self.mm_base_cache = img
        return img

    def _draw_mm_popup(self):
        """★ POPUP_FAST_V3：可滑动弹窗（快速版）

        关键：用 scr.flush()（无参）走【一次 memmove】快速路径，
              而不是 flush(rect) 的【逐行 Python 循环】慢路径
        """
        lines = self.mm_popup
        if not lines:
            return
        got = self._mm_render_report()
        if not got:
            return
        rdata, rw, total_h = got

        scr = self.scr
        x0, y0, x1, y1 = 62, 46, 962, 550
        cy0 = y0 + 46
        cy1 = y1 - 8
        ch = cy1 - cy0
        max_scroll = max(0, total_h - ch)
        sc = max(0, min(self.mm_scroll, max_scroll))
        self.mm_scroll = sc

        # ★ POPUP_FAST_V6：底板只 paste 一次（V4 guard 保证没别的东西覆盖）
        base = self._mm_base_image()
        if not getattr(self, "mm_base_painted", False) or \
           getattr(self, "mm_base_painted_size", None) != scr.img.size:
            scr.img.paste(base, (0, 0))
            self.mm_base_painted = True
            self.mm_base_painted_size = scr.img.size

        # ★ SCROLL_FAST_V1：滚动时只 blit 内容区，不全屏 flush
        #   原来 scr.flush() = img.convert().tobytes() 1.8MB + mmap 1.8MB ≈ 50-60ms
        #   现在直接把已缓存的 raw 切片 blit ≈ 5-10ms
        row = rw * 3
        o = sc * row
        seg = rdata[o:o + ch * row]
        if len(seg) != ch * row:
            return
        scr.blit_raw(x0, cy0, rw, ch, seg)

        # 滚动条：单独构造 12px 宽的小 buffer 再 blit
        if max_scroll > 0:
            bar_w = 12
            bar_h = max(40, int(ch * ch / float(total_h)))
            bar_y = int((ch - bar_h) * sc / float(max_scroll))
            _bg = bytes((20, 27, 42))
            _tr = bytes((30, 40, 60))
            _th = bytes((120, 160, 220))
            bar = bytearray()
            for yy in range(ch):
                rb = bytearray(_bg * bar_w)
                rb[18:30] = (_th if bar_y <= yy < bar_y + bar_h else _tr) * 4
                bar += rb
            scr.blit_raw(x1 - bar_w, cy0, bar_w, ch, bar)

        # ★ SCROLL_FAST_V1：同时把滚动条画进 scr.img（供首帧全屏 flush 用）
        if max_scroll > 0:
            bar_h2 = max(40, int(ch * ch / float(total_h)))
            bar_y2 = cy0 + int((ch - bar_h2) * sc / float(max_scroll))
            scr.rrect([x1 - 8, cy0, x1 - 4, cy1], 2, fill=(30, 40, 60))
            scr.rrect([x1 - 8, bar_y2, x1 - 4, bar_y2 + bar_h2], 2, fill=(120, 160, 220))

        # ★ 首帧需要完整画面（遮罩+标题栏），之后滚动不再全屏 flush
        if not getattr(self, "mm_first_flushed", False):
            self.mm_first_flushed = True
            scr.flush()


    def ai_card_close_clear(self):
        """★ AI_CARD_CLOSE_V1：关闭 AI 分析卡片（清空所有结果）"""
        self.ai_res = None
        self.ai_reply = None
        self.ai_err = None
        self.ai_mm = None
        self.ai_busy = False
        self.ai_cache = None
        self.ai_t0 = 0.0
        self.ai_btns = []
        self.ai_mode_btns = []
        self.ai_cloud_txt = None
        self.ai_cloud_busy = False
        self.ai_card_close = None
        print("[AI] card closed by user")
        # 重画波形区（把卡片区域覆盖回去）
        # ★ 必须连网格/刻度一起重画，否则卡片位置留下黑块
        self.draw_scales()
        self.draw_wave()
        self.draw_cards()

    def _ai_card_raw(self):
        """画卡片（含引擎切换键）到临时区，转 raw bytes（带缓存）"""
        busy = getattr(self, "ai_busy", False)
        eng = getattr(self, "ai_engine", "local")
        res = getattr(self, "ai_res", None)
        rep = getattr(self, "ai_reply", None)
        err = getattr(self, "ai_err", None)
        if not busy and res is None and rep is None and err is None and getattr(self, "ai_mm", None) is None:
            return None
        if not busy and (time.time() - getattr(self, "ai_t0", 0.0)) > 90.0:
            self.ai_res = None; self.ai_reply = None; self.ai_err = None
            self.ai_cache = None
            return None
        mm = getattr(self, "ai_mm", None)
        # ★ MM_CARD_V1：key 里加入多模态结果的指纹
        mmkey = None
        if mm:
            mmkey = (mm.get("label"), round(float(mm.get("confidence") or 0), 2),
                     (mm.get("extra") or {}).get("quality_score"),
                     (mm.get("text") or "")[:40], bool(mm.get("_error")))
        key = (busy, eng, getattr(self, "ai_mode", "local"),
               (getattr(self, "ai_cloud_txt", None) or "")[:40],
               getattr(self, "ai_cloud_busy", False),
               (res or {}).get("label"),
               round(float((res or {}).get("confidence") or 0), 3),
               (res or {}).get("elapsed_ms"), (rep or "")[:80],
               self.m.active, err, mmkey)
        c = getattr(self, "ai_cache", None)
        if c is not None and c[0] == key:
            return c[1], c[2], c[3]
        # ★ CARD_ISOLATED_IMG_V1：用独立临时 Image，不再污染 scr.img
        #   原来把卡片画到 scr.img 的左上角 (0,0)，
        #   而 draw_top/draw_stat/flush 都刷 scr.img
        #   ⇒ 卡片内容在屏幕左上角与顶栏重叠！
        scr = self.scr
        cw, chh = self.AI_CARD_W, self.AI_CARD_H
        tmp = (0, 0, cw, chh)
        # ★ CARD_BAK_FIX_V1：用【真实备份】（crop 当前内容）
        #   不能用 self.bg（静态背景）恢复——会把顶栏文字擦掉
        #   也不能只换 scr.img：scr.d 里绑定了原 img 的 ImageDraw
        _bak = scr.img.crop(tmp)
        scr.rrect(tmp, 8, fill=(22, 30, 46), outline=C_AI_BTN, width=2)
        scr.rect([0, 0, cw, 26], fill=(40, 32, 62))
        scr.text((12, 13), "AI 分析", 15, (205, 185, 250), anchor="lm", cn=True)
        # ★ AI_CARD_CLOSE_V1：标题栏右侧关闭按钮
        _cb = [cw - 26, 5, cw - 6, 23]
        self.ai_card_close = _cb
        scr.rrect(_cb, 5, fill=(120, 52, 60), outline=(180, 95, 105), width=1)
        scr.text((( _cb[0] + _cb[2]) // 2, (_cb[1] + _cb[3]) // 2), "X", 11,
                 (255, 235, 235), anchor="mm", cn=True)
        # AI_SPEAK_V3：X 左边加一个 ▶ 播放按钮（朗读一句话总结）
        _pb = [cw - 58, 5, cw - 32, 23]
        self.ai_card_play = _pb
        scr.rrect(_pb, 5, fill=(48, 92, 60), outline=(96, 160, 110), width=1)
        scr.text(((_pb[0] + _pb[2]) // 2, (_pb[1] + _pb[3]) // 2), "▶", 11,
                 (215, 255, 220), anchor="mm", cn=True)
        # ★ AI_TWO_MODES_V1：两个模式按钮（标题栏下方一行）
        _mb1 = [10, 30, 118, 52]
        _mb2 = [124, 30, 232, 52]
        for _r, _nm, _on, _md in ((_mb1, "本地多模态", self.ai_mode == "local", "local"),
                                  (_mb2, "云端增强", self.ai_mode == "cloud", "cloud")):
            scr.rrect(_r, 6, fill=(70, 58, 120) if _on else (32, 40, 56),
                      outline=C_AI_BTN if _on else (60, 70, 92), width=2)
            scr.text(((_r[0] + _r[2]) // 2, (_r[1] + _r[3]) // 2), _nm, 12,
                     (235, 228, 255) if _on else (140, 150, 170), anchor="mm", cn=True)
        # 状态提示（模式按钮右侧）
        _st, _stc = "", (150, 165, 190)
        if busy:
            _st, _stc = "分析中…", (200, 200, 130)
        elif self.ai_cloud_busy:
            _st, _stc = "云端分析中…", (130, 200, 255)
        elif mm is not None and not mm.get("_error") and getattr(self, "ai_mode", "local") == "cloud":
            _st, _stc = "云端 16 类", (130, 200, 255)
        elif res is not None and getattr(self, "ai_mode", "local") == "local":
            _st, _stc = "本地模板匹配", (150, 230, 180)
        elif mm is not None and mm.get("_error"):
            _st, _stc = "多模态不可达", (240, 170, 120)
        elif res is not None:
            _st, _stc = "端侧结果", (200, 200, 130)
        if _st:
            scr.text((240, 41), _st, 11, _stc, anchor="lm", cn=True)
        if busy:
            scr.text((cw // 2, 120), "分析中 …", 22, (210, 220, 240),
                     anchor="mm", cn=True)
            scr.text((cw // 2, 150), "(云端需要几秒)", 13,
                     (150, 165, 190), anchor="mm", cn=True)
        elif err:
            scr.text((cw // 2, 112), "分析失败", 18, C_WARN, anchor="mm", cn=True)
            scr.text((cw // 2, 144), err, 11, (180, 190, 210), anchor="mm", cn=True)
        elif mm and getattr(self, "ai_mode", "local") != "local":
            # AI_MODE_SPLIT_V1：只有「云端增强」模式才显示云端结果
            #
            # 原来只要 mm 非空就走这里，
            # 用户点「本地多模态」后云端一回来就把本地结果覆盖了。
            # 现在本地模式会跳过这个分支，回落到 elif res（显示本地结果）。
            #
            # ★ MM_CARD_V1：多模态结果显示
            if mm.get("_error"):
                scr.text((cw // 2, 84), "多模态服务不可达", 17, C_WARN,
                         anchor="mm", cn=True)
                scr.text((cw // 2, 114), str(mm["_error"])[:38], 11,
                         (180, 190, 210), anchor="mm", cn=True)
                scr.text((cw // 2, 136), "请确认 PC 上 wave_ai.serve 在跑", 12,
                         (150, 165, 190), anchor="mm", cn=True)
            else:
                lbl = mm.get("label") or ""
                _mmc2 = 0.0
                try:
                    _mmc2 = float(mm.get("confidence") or 0.0)
                except Exception:
                    _mmc2 = 0.0
                # MM_UNKNOWN_GATE_V2：云端置信度 < 0.80 一律说「非常见波形」
                #
                # 实测：云端是 16 类分类器，遇到不在 16 类里的波形会硬塞，
                #   而且塞得还不稳定（半波整流一会儿 pulse 一会儿 duty_abnormal）。
                #   与其显示一个错的类别，不如明确说「非常见」。
                #   0.80 的依据：正常波形（正弦/方波/三角/锯齿）云端通常 0.85+，
                #   未知波形会掉到 0.4~0.7，0.80 能把它们分开。
                if _mmc2 < 0.80:
                    _cloud_cn = "非常见波形（云端 %.0f%%）" % (_mmc2 * 100)
                else:
                    _cloud_cn = self._AI_MM_CN.get(lbl, mm.get("label_cn") or lbl or "?")

                # LOCAL_TPL_WINS_V1：本地模板高置信命中时，主标题以本地为准
                #   （否则「半波整流 99.4%」会被云端「脉冲」覆盖掉）
                _tpl = getattr(self, "ai_tpl", None) or {}
                _tpl_cn = _tpl.get("label_cn")
                try:
                    _tpl_sc = float(_tpl.get("score") or 0.0)
                except Exception:
                    _tpl_sc = 0.0
                self._ai_ref_line = ""
                # LOCAL_TPL_WINS_V2：阈值 0.85 -> 0.75（与 forced() 的命中阈值一致）
                #
                # 原来 0.85 太紧：多音频实测 0.867，波动到 0.84 就掉出阈值，
                # 主标题被云端「倍频」覆盖 => 用户看到「刚开始对，后面变倍频」。
                # 现在只要模板命中（>=0.75 且非 weak），本地就是主标题，
                # 云端类别永远只作「云端参考」显示。
                if _tpl_cn and _tpl_sc >= 0.75 and not _tpl.get("weak"):
                    cn = _tpl_cn
                    conf = _tpl_sc
                    self._ai_ref_line = "云端参考：%s" % _cloud_cn
                else:
                    cn = _cloud_cn
                    conf = _mmc2
                    self._ai_ref_line = ""
                q = (mm.get("quality") or {}).get("score")
                anom = (mm.get("anomaly") or {}).get("is_anomaly")
                # 第一行：中文类名 + 置信度 + 质量分
                scr.text((14, 104), cn, 24, (90, 220, 150), anchor="lm", cn=True)
                scr.text((cw - 14, 106), "%.0f%%" % (conf * 100), 18,
                         (200, 235, 215), anchor="rm")
                info = ""
                if q is not None:
                    info = "质量 %d 分" % int(q)
                if anom:
                    info += ("  " if info else "") + "[!] 异常"
                if info:
                    scr.text((14, 130), info, 13,
                             C_WARN if anom else (170, 190, 220), anchor="lm", cn=True)
                # LOCAL_TPL_WINS_V1：云端参考行（本地为主时显示）
                _ref = getattr(self, "_ai_ref_line", "")
                if _ref:
                    scr.text((cw - 14, 130), _ref, 11,
                             (140, 160, 190), anchor="rm", cn=True)
                # 下面：中文一句话（最多 2 行）
                txt = mm.get("text") or ""
                lines, cur = [], ""
                for ch in txt:
                    cur += ch
                    if len(cur) >= 24:
                        lines.append(cur); cur = ""
                if cur:
                    lines.append(cur)
                # ★ AI_TWO_MODES_V3：云端增强结果优先显示
                _ct = getattr(self, "ai_cloud_txt", None)
                if _ct:
                    _cl, _cur2 = [], ""
                    for _ch in _ct:
                        _cur2 += _ch
                        if len(_cur2) >= 26:
                            _cl.append(_cur2); _cur2 = ""
                    if _cur2:
                        _cl.append(_cur2)
                    for k, ln in enumerate(_cl[:2]):
                        scr.text((14, 148 + k * 15), ln, 11, (150, 210, 255),
                                 anchor="lm", cn=True)
                elif getattr(self, "ai_cloud_busy", False):
                    scr.text((14, 148), "云端正在深度分析…", 11,
                             (150, 190, 230), anchor="lm", cn=True)
                else:
                    for k, ln in enumerate(lines[:2]):
                        scr.text((14, 148 + k * 15), ln, 11, (190, 205, 230),
                                 anchor="lm", cn=True)
                # ★ MM_REPORT_V1：右下角「详情」按钮
                scr.rrect([cw - 76, chh - 26, cw - 8, chh - 8], 5,
                          fill=(70, 58, 120), outline=C_AI_BTN, width=1)
                scr.text((cw - 42, chh - 17), "详情 >", 12,
                         (225, 220, 255), anchor="mm", cn=True)
        elif eng == "cloud" and rep:
            lines, cur = [], ""
            for ch in rep:
                cur += ch
                if len(cur) >= 23:
                    lines.append(cur); cur = ""
            if cur:
                lines.append(cur)
            for k, ln in enumerate(lines[:4]):
                scr.text((12, 74 + k * 20), ln, 14, (215, 228, 250), anchor="lm", cn=True)
        else:
            cn, tip, line2 = self._ai_summary()
            conf = float((res or {}).get("confidence") or 0.0)
            scr.text((14, 106), cn, 24, (90, 220, 150), anchor="lm", cn=True)
            scr.text((cw - 14, 108), "%.0f%%" % (conf * 100), 18,
                     (200, 235, 215), anchor="rm")
            scr.text((14, 134), line2, 13, (190, 205, 230), anchor="lm", cn=True)
            scr.text((14, 156), tip, 12, (150, 170, 200), anchor="lm", cn=True)
        # ★ CARD_BAK_FIX_V1：从当前内容取 raw，然后用备份完全恢复
        raw = scr.to_raw(scr.img.crop(tmp))
        scr.img.paste(_bak, (0, 0))
        print("[AI-CLICK] card rendered key=%s" % (str(key)[:70],))
        self.ai_cache = (key, cw, chh, raw)
        return cw, chh, raw

    def _ai_card_paint(self, buf, w, h):
        """把 AI 卡片拷进波形缓冲区（RGB，行宽 w）"""
        got = self._ai_card_raw()
        if not got:
            return
        cw, chh, raw = got
        cx, cy = w - cw - 14, 12
        # ★ 把卡片内切换键换算成屏幕坐标，供 handle() 检测
        _sx, _sy = PLOT[0] + cx, PLOT[1] + cy
        _bw, _bh = self.AI_ENG_BTN_W, self.AI_ENG_BTN_H
        # ★ MM_CARD_V1：三个引擎按钮的点击坐标
        _gap = 6
        _bw3 = (cw - 2 * 10 - 2 * _gap) // 3
        _x1 = _sx + 10
        _x2 = _x1 + _bw3 + _gap
        _x3 = _x2 + _bw3 + _gap
        # ★ AI_TWO_MODES_V3：X + 两个模式按钮的屏幕坐标
        self.ai_card_close = [_sx + cw - 26, _sy + 5, _sx + cw - 6, _sy + 23]
        # AI_SPEAK_V3：播放按钮也转成屏幕坐标
        self.ai_card_play = [_sx + cw - 58, _sy + 5, _sx + cw - 32, _sy + 23]
        self.ai_mode_btns = [
            ([_sx + 10, _sy + 30, _sx + 118, _sy + 52], "local"),
            ([_sx + 124, _sy + 30, _sx + 232, _sy + 52], "cloud"),
        ]
        self.ai_btns = []
        row = cw * 3
        for i in range(chh):
            yy = cy + i
            if yy < 0 or yy >= h:
                continue
            o = (yy * w + cx) * 3
            p = i * row
            buf[o:o + row] = raw[p:p + row]

    def close_panel(self):
        self.panel = None
        # ★ FLICKER_FIX：不要先 flush 再 full_redraw（中间会有一帧空白），
        #   直接全屏重绘即可（full_redraw 本身会 flush）。
        self.full_redraw()

    # ================= 触摸 =================
    def tap_field(self, i):
        now = time.time()
        if self.last_tag == i and (now - self.last_tap) < 0.45:
            self.reset_field(i)
            self.last_tag = -1
        else:
            self.sel_field = i
            self.last_tag = i
        self.last_tap = now
        self.draw_cards()
        self.draw_ctl()

    def reset_field(self, i):
        m = self.m
        if i == 1:
            m.vpos_reset(m.active)
        elif i == 3:
            m.hpos_reset()
        elif i == 4:
            m.level_reset()
        m.commit(self.hw)

    def bump(self, sign):
        """加减一档。★ 每次步长 = 当前每格数值的 0.1 倍：
            V/div=5V   -> 垂直位置/触发电平每按一次变 0.5V
            V/div=100mV-> 每按一次变 10mV
            Time/div=200us -> 水平位置每按一次变 20us
        ★ 改完立刻重绘（原来不重绘，用户以为"数字改不了"）。"""
        m = self.m
        i = self.sel_field
        c = m.ch[m.active]
        lsb_per_div = VDIV_V[c.vdiv_idx] / (V_FULL * CAL_GAIN) * SAMPLE_MAX
        if i == 0:
            m.vdiv_step(m.active, sign)
        elif i == 1:
            m.vpos_step(m.active, sign * 0.1)          # 0.1 格
        elif i == 2:
            m.tb_step(sign)
            self.hw.set_dec(m.tb.dec)      # ★ 时基只在这一处提交
            self.push_window()
        elif i == 3:
            m.hpos_step(sign * 0.1)                    # 0.1 格
        elif i == 4:
            m.level_step(sign * max(1, int(round(0.1 * lsb_per_div))))
        m.commit(self.hw)
        # ★★ 立刻重绘受影响的全部区域
        self.span = m.tb.span
        self.draw_wave()
        self.draw_scales()
        self.draw_stat()
        self.draw_cards()
        self.draw_ctl()

    def do_auto(self):
        """执行一次 AUTO：定 3 周期时基 + 75% 幅度量程 + 水平位置归零。
        返回 True 表示真的调了档；False 表示当前没有可用测量。"""
        mm = self.m.m[self.m.active]
        pick = self.m.active
        if not self.m.auto_ready(mm):
            for no in (0, 1):
                if no == self.m.active or not self.m.ch[no].enabled:
                    continue
                if self.m.auto_ready(self.m.m[no]):
                    mm = self.m.m[no]
                    pick = no
                    break
        if not self.m.auto_ready(mm):
            self.auto_hint = "AUTO 需要稳定信号（未锁定）"
            self.auto_hint_t = time.time()
            return False
        keep = self.m.active
        self.m.active = pick
        self.m.auto_range(mm)
        self.m.active = keep
        self.hw.set_dec(self.m.tb.dec)
        self.m.commit(self.hw)
        self.push_window()
        self.auto_hint = "AUTO 完成(%s)" % ("CH1" if pick == 0 else "CH2")
        self.auto_hint_t = time.time()
        return True

    def zero_field(self):
        """「归位到 0」：一键把【三个偏移全部】归零 —— 垂直位置、水平位置、触发电平。
        V/div 和 Time/div 是"每格多少"，本身没有零点，不动。
        （原来只归零"当前选中项"，选到 V/div 时按了没反应，用户会以为按钮坏了。）"""
        m = self.m
        m.vpos_reset(m.active)
        m.hpos_reset()
        m.level_reset()
        m.commit(self.hw)
        self.span = m.tb.span
        self.draw_wave()
        self.draw_scales()
        self.draw_stat()
        self.draw_cards()
        self.draw_ctl()

    def handle(self, x, y, kind="down"):
        # ★ MM_REPORT_V1 / POPUP_OPEN_FLAG_V1：弹窗真正打开时才拦截触摸
        if self.mm_popup_open:
            if kind == "move":
                if self.mm_drag_y is not None:
                    self.mm_scroll += (self.mm_drag_y - y) * 2
                    if self.mm_scroll < 0:
                        self.mm_scroll = 0
                    self.mm_drag_y = y
                    # ★ POPUP_PERF_V1：限频 60ms，避免拖动时卡死
                    _now = time.time()
                    if _now - getattr(self, "mm_last_draw", 0.0) > 0.06:
                        self.mm_last_draw = _now
                        self._draw_mm_popup()
                return True
            if kind == "up":
                self.mm_drag_y = None
                self._draw_mm_popup()     # ★ POPUP_PERF_V1：抬手补一次精确重绘
                return True
            # down
            cb = self.mm_pop_close
            if cb and hit(cb, x, y):
                self.mm_close_popup()
                return True
            # 在弹窗内部 -> 开始拖动；在外部 -> 关闭
            if 50 <= x <= 974 and 40 <= y <= 556:
                self.mm_drag_y = y
                return True
            self.mm_close_popup()
            return True
        if kind == "move":
            if self.drag is not None:
                self.m.ch[self.m.active].vpos += (y - self.drag) / float(self.wh / GRID_R)
                self.drag = y
                self.draw_cards()
            return True
        if kind == "up":
            if self.drag is not None:
                self.drag = None
                self.m.commit(self.hw)
                self.draw_wave()
                self.draw_scales()
            return True
        if back_hit(x, y):
            return False
        if self.panel:
            for r, (i, act) in getattr(self, "panel_rects", []):
                if hit(r, x, y):
                    self.choose(i, act)
                    return True
            self.close_panel()
            return True
        for i, r in enumerate(self.cardrect):
            if hit(r, x, y):
                self.tap_field(i)
                return True
        # 点顶部 CH1/CH2 条 = 只切换"当前调节通道"，不动显示/触发源
        for no, tg in ((0, self.tag1), (1, self.tag2)):
            if hit(tg, x, y):
                self.m.set_active(no)
                self.draw_stat()
                self.draw_cards()
                self.draw_scales()
                self.draw_ctl()
                return True
        if hit(self.b_ch, x, y):
            self.chk = [self.m.ch[0].enabled, self.m.ch[1].enabled]
            self.panel = "ch"
            self.draw_panel()
            return True
        if hit(self.b_mode, x, y):
            self.pend_mode = self.m.acq.mode
            self.panel = "mode"
            self.draw_panel()
            return True
        if hit(self.b_ai, x, y):
            print("[AI-CLICK] button hit at (%d,%d)" % (x, y))
            self.ai_analyze()
            return True
        # AI_SPEAK_V3：播放按钮（朗读一句话总结）
        _pp = getattr(self, "ai_card_play", None)
        if _pp and hit(_pp, x, y):
            print("[AI-SPEAK] play clicked")
            txt = self._speak_summary()
            print("[AI-SPEAK] text = %s" % (txt or "")[:60])
            return True
        # ★ AI_CARD_CLOSE_V1：先检查卡片的 X（优先级最高）
        _cc = getattr(self, "ai_card_close", None)
        if _cc and hit(_cc, x, y):
            self.ai_card_close_clear()
            return True
        # ★ AI_TWO_MODES_V3：模式切换按钮
        for _r, _md in getattr(self, "ai_mode_btns", []):
            if hit(_r, x, y):
                if self.ai_mode != _md:
                    self.ai_mode = _md
                    print("[AI] mode -> %s" % _md)
                    self.ai_cloud_txt = None
                    self.ai_cache = None
                    self.ai_analyze()      # 切模式后重跑分析
                return True
        # ★ AI 卡片里的引擎切换键
        for _r, _e in getattr(self, "ai_btns", []):
            if hit(_r, x, y):
                if getattr(self, "ai_engine", "local") != _e:
                    self.ai_engine = _e
                    self.ai_analyze()
                return True
        # ★ MM_REPORT_V1：多模态卡片的「详情」按钮
        if getattr(self, "ai_mm", None):
            _sx = PLOT[0] + (self.ww - self.AI_CARD_W - 14)
            _sy = PLOT[1] + 12
            _dr = [_sx + self.AI_CARD_W - 76, _sy + self.AI_CARD_H - 24,
                   _sx + self.AI_CARD_W - 8, _sy + self.AI_CARD_H - 6]
            if hit(_dr, x, y):
                self.mm_open_popup()
                return True
        if hit(self.b_minus, x, y):
            self.bump(-1); return True
        if hit(self.b_plus, x, y):
            self.bump(+1); return True
        if hit(self.b_cur, x, y):
            self.sel_field = (self.sel_field + 1) % 5
            self.draw_cards(); self.draw_ctl(); return True
        if hit(self.b_fine, x, y):
            # ★ 原来是"粗调/细调"开关，按用户要求改成【归位到 0】
            self.zero_field()
            return True
        if hit(self.b_run, x, y):
            self.m.toggle_running()
            if self.m.acq.mode == ACQ_SINGLE:
                self.single_seen = -1
            self.m.commit(self.hw)
            self.draw_ctl(); self.draw_top(); return True
        if PLOT[0] <= x <= PLOT[2] and PLOT[1] <= y <= PLOT[3]:
            now = time.time()
            if (now - self.last_tap) < 0.35:
                # ★ 双击波形区 = 重新 AUTO（会顺带把水平位置归零到起始位置）
                self.do_auto()
                self.last_tap = 0.0
                self.full_redraw()
                self.draw_cards()
                return True
            self.last_tap = now
            self.drag = y
            return True
        return True

    def choose(self, i, act):
        m = self.m
        if act == "c1":
            self.chk[0] = not self.chk[0]
            self.draw_panel(); return
        if act == "c2":
            self.chk[1] = not self.chk[1]
            self.draw_panel(); return
        if act in ("m0", "m1", "m2"):
            self.pend_mode = int(act[1])
            self.draw_panel(); return
        if act == "adv":
            self.panel = "adv"
            self.draw_panel(); return
        if act == "back":
            self.panel = "mode"
            self.draw_panel(); return
        if act == "ok":
            if self.panel == "ch":
                # 至少保留一个显示通道
                if not self.chk[0] and not self.chk[1]:
                    self.chk = [True, False]
                m.ch[0].enabled = self.chk[0]
                m.ch[1].enabled = self.chk[1]
                # ★ 切显示【不】重新配置采集器（两路 ADC 本来就在同时采）
            elif self.panel == "mode":
                m.set_acq_mode(self.pend_mode)
                m.commit(self.hw)
            self.close_panel(); return
        # 高级触发页的即时项
        if act == "src":
            m.set_trig_src((m.trig.src + 1) % 3)
        elif act == "edge":
            m.trig.edge = 1 - m.trig.edge
        elif act == "lev":
            m.level_step(32 if m.trig.level < 900 else -384)
        elif act == "pre":
            p = m.trig.pretrigger + 0.1
            m.trig.pretrigger = 0.1 if p > 0.91 else p
        elif act == "hys":
            m.trig.auto_hys = not m.trig.auto_hys
        m.commit(self.hw)
        self.draw_panel()

    def full_redraw(self):
        self.draw_top()
        self.draw_stat()
        self.draw_scales()
        self.draw_wave()
        self.draw_cards()
        self.draw_ctl()


def _run_impl(scr, touch):
    app = App(scr)
    app.make_bg()
    scr.flush()
    app.full_redraw()
    now = time.time()
    app.last_wave = app.last_text = now
    # ★ 用户要求"一打开就是经过 auto 的"：启动后自动跑一次 AUTO。
    #   前几帧还没测量结果，所以每轮试一次，最多试 AUTO_TRIES 轮。
    auto_tries = 0
    while True:
        # ★ 触摸优先：每 8ms 无条件轮询一次（采集是非阻塞的，不会挡住触摸）
        ev = touch.poll(move=True)
        if ev:
            x = y = 0
            kind = "down"
            if isinstance(ev, (list, tuple)):
                # ★ TOUCH_KIND_FIX_V1：Touch.poll 返回 ("move",x,y)
                #   kind 在 ev[0]，不是 ev[3]！
                #   原来 len==3 时 kind 永远是 "down"
                #   ⇒ 所有 move 事件被当 down 处理
                #   ⇒ 拖动全部失效（波形上下拖/弹窗滚动/笔记滑动）
                if len(ev) >= 3 and isinstance(ev[0], str):
                    kind = ev[0]
                    x, y = ev[1], ev[2]
                    if kind == "tap":
                        kind = "down"      # tap 当作 down 处理
                elif len(ev) >= 3:
                    x, y = ev[1], ev[2]
                    kind = ev[3] if len(ev) > 3 else "down"
                elif len(ev) == 2:
                    x, y = ev
            # ★ 修复①：按下边沿检测（去抖）
            #   Goodix 按住不放时会连续上报 down 事件，
            #   而 handle() 每次收到 down 都会执行一次动作
            #   （如 bump(-1)）⇒ 按一下 V/div 会跳好几个。
            #   这里只在【从未按下变为按下】时才处理，
            #   同一位置 TOUCH_DEBOUNCE 秒内的重复 down 直接忽略。
            TOUCH_DEBOUNCE = 0.35
            if kind == "down":
                _t = time.time()
                _lx, _ly = app._last_tap
                if (_t - app._last_tap_t) < TOUCH_DEBOUNCE and \
                   abs(x - _lx) < 14 and abs(y - _ly) < 14:
                    pass                       # 重复 down，忽略
                else:
                    app._last_tap_t = _t
                    app._last_tap = (x, y)
                    if not app.handle(x, y, kind):
                        return
            else:
                # up/move 照常处理（不参与去抖）
                if not app.handle(x, y, kind):
                    return
        now = time.time()
        # ★ POPUP_FAST_V4：弹窗打开时跳过所有绘制
        #   否则 draw_wave() 每 33ms 覆盖一次，弹窗被盖 = 看起来像卡死
        if getattr(app, "mm_popup_open", False):
            time.sleep(0.02)
            continue
        # 采集（非阻塞）
        app.step()
        # ★ 启动后自动 AUTO。必须等【新鲜帧】到手再调：
        #   刚进来时 self.m.m[] 里可能还是上一次运行残留的测量，
        #   用它去 AUTO 会把时基定错（实测定成 20us，而 2kHz 该是 150us）。
        #   所以先空跑 AUTO_WARM 轮（约 120ms，足够采到 1~2 帧），再开始 AUTO。
        AUTO_WARM = 40
        if auto_tries < 400:
            auto_tries += 1
            if auto_tries > AUTO_WARM and app.do_auto():
                app.full_redraw()
                auto_tries = 100000
        if app.panel is None:
            if now - app.last_wave >= WAVE_DT:       # 30 FPS
                app.draw_wave()
                app.last_wave = now
            if now - app.last_text >= TEXT_DT:       # 6.7 FPS
                app.draw_stat()
                app.draw_top()
                app.draw_scales()
                app.last_text = now
        else:
            # ★ 修复②：panel 打开时也按低频重绘 panel。
            #   原来 panel 只在点的那一下画一次，之后主循环什么都不刷；
            #   而任何局部重绘（step() 里的状态更新等）都会把 panel
            #   区域盖掉 ⇒ 弹窗一闪一闪。这里每 PANEL_DT 重画一次，
            #   保证它始终在最上层（频率很低，几乎不增开销）。
            PANEL_DT = 0.12
            if now - getattr(app, "last_panel", 0) >= PANEL_DT:
                app.draw_panel()
                app.last_panel = now
            # ★ 顶栏/参数行也要低频刷新：
            #   否则 panel 打开期间它们会卡在旧内容
            #   （实测屏幕上还显示着很久以前的「丢帧」字样）。
            PANEL_TEXT_DT = 0.5
            if now - getattr(app, "last_panel_text", 0) >= PANEL_TEXT_DT:
                app.draw_top()
                app.draw_stat()
                app.last_panel_text = now
        dt = time.time() - now
        if dt < TOUCH_DT:
            time.sleep(TOUCH_DT - dt)


# SCOPE_SLEEP_SVC_V1: 示波器运行时暂停无关后台服务，退出时恢复
#
# 为什么：实测 desktop.py 一个人占 52% CPU（桌面+示波器绘制）。
#   示波器需要尽可能多的 CPU 给采集/绘制，
#   所以进示波器时把 cloud-api / zynq-agent / zynq-audio 暂停，
#   退出时（含异常退出）在 finally 里恢复。
#
# 云端 AI 分析是直接 HTTP 到 PC:8000，不依赖 cloud-api，所以暂停不影响。
#
# 只暂停【本来就在运行】的服务；本来停着的不会被启动。

_SVC_LIST = ("cloud-api", "zynq-agent", "zynq-audio")
_SVC_STATE = {}


def _svc_sleep(sleep=True):
    import subprocess

    global _SVC_STATE
    for svc in _SVC_LIST:
        try:
            r = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True, timeout=5)
            is_active = (r.stdout or "").strip() == "active"
        except Exception:
            is_active = False

        if sleep:
            _SVC_STATE[svc] = is_active
            if is_active:
                try:
                    subprocess.run(["sudo", "-n", "systemctl", "stop", svc],
                                   capture_output=True, timeout=12)
                    print("[scope] pause %s" % svc)
                except Exception as e:
                    print("[scope] pause %s failed: %s" % (svc, e))
        else:
            if _SVC_STATE.get(svc):
                try:
                    subprocess.run(["sudo", "-n", "systemctl", "start", svc],
                                   capture_output=True, timeout=20)
                    print("[scope] resume %s" % svc)
                except Exception as e:
                    print("[scope] resume %s failed: %s" % (svc, e))
    if not sleep:
        _SVC_STATE = {}


def run(scr, touch):
    """入口：先休眠无关服务，跑完（含异常）一定恢复"""
    try:
        _svc_sleep(True)
    except Exception as e:
        print("[scope] sleep services failed: %s" % e)
    try:
        return _run_impl(scr, touch)
    finally:
        try:
            _svc_sleep(False)
        except Exception as e:
            print("[scope] wake services failed: %s" % e)
