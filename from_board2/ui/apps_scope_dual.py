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
import time

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
        self.chk = [True, False]   # 弹层里的复选暂存
        self.pend_mode = ACQ_AUTO
        self.last_wave = 0.0
        self.last_text = 0.0
        self.last_net = 0.0
        self.net_ok = True
        self.warn = ["", ""]        # 过量程提示
        self.n, self.t_win, self.fps = 0, time.time(), 0.0
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
            self.n, self.t_win = 0, time.time()

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
        return {"min": mn, "max": mx, "mid": (mn + mx) // 2, "pp": mx - mn,
                "edges": ed, "mean": s / float(n),
                "period": per * dt if per else None,
                "freq": None if tiny else ((1.0 / (per * dt)) if (per and per > 0) else None),
                "duty": 0.0 if tiny else (hi * 100.0 / n),
                "vpp": c.to_volt(mx) - c.to_volt(mn),   # ★ 直接用 to_volt 相减，避免 gain/probe 被乘两次
                "vmax": c.to_volt(mx), "vmin": c.to_volt(mn),
                "locked": bool(ed >= 2) and not tiny,
                "over": (lo + hi) >= (n // 64) or lo >= 16 or hi >= 16,
                "sat_lo": lo, "sat_hi": hi}

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

        widths = [176, 176, 138, 132, 138, 130, 118]
        xs, acc = [], 8
        for wd in widths:
            xs.append([acc, CTL_Y, acc + wd, CTL_Y + CTL_H])
            acc += wd + 6
        (self.b_ch, self.b_mode, self.b_minus, self.b_cur,
         self.b_plus, self.b_fine, self.b_run) = xs
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
            scr.text((566, TOP_H // 2), "丢帧%d" % m.lost, 15,
                     (220, 120, 110) if m.lost else C_DIM, anchor="lm", cn=True)
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
                vals = [("%.2fV" % mm.get("vpp", 0), (255, 214, 140)),
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
                  (168, 68, 68) if m.running else C_SEL)]
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
        scr.img.paste(self.bg.crop(CLEAN), (CLEAN[0], CLEAN[1]))
        scr.flush(box=CLEAN)
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
        scr.flush(box=(x - 6, y - 6, x + cw + 6, y + total + 6))

    def close_panel(self):
        self.panel = None
        CLEAN = (0, PLOT[1] - 4, 320, CTL_Y)
        self.scr.img.paste(self.bg.crop(CLEAN), (CLEAN[0], CLEAN[1]))
        self.scr.flush(box=CLEAN)
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


def run(scr, touch):
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
                if len(ev) >= 3:
                    x, y = ev[1], ev[2]
                    kind = ev[3] if len(ev) > 3 else "down"
                elif len(ev) == 2:
                    x, y = ev
            if not app.handle(x, y, kind):
                return
        now = time.time()
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
        dt = time.time() - now
        if dt < TOUCH_DT:
            time.sleep(TOUCH_DT - dt)
