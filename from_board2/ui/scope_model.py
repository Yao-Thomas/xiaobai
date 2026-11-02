#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_model.py —— 全部配置状态（不含硬件、不含 UI）

按用户方案：UI 只读写 ScopeModel，配置变更通过一次原子 commit() 提交给 PL，
避免"一个配置更新到一半就开始采集"。

三个概念必须分开（用户特别强调）：
    · 显示通道 display   —— 波形画不画
    · 当前调节通道 active —— 面板上的 －/＋ 改谁
    · 触发源 trig.src     —— 拿谁做触发
点击"显示 CH2"绝不能顺手改掉触发源。
"""
from scope_processing import Timebase, ChannelCal, TIME_DIV, V_FULL, SAMPLE_MAX

# 采集模式（Roll 是采集模式，不是触发源）
ACQ_AUTO, ACQ_NORMAL, ACQ_SINGLE, ACQ_ROLL = 0, 1, 2, 3
ACQ_NAMES = ["AUTO", "NORMAL", "SINGLE", "ROLL"]
ACQ_DESC = ["有触发用触发位置，超时也刷新并标未锁定",
            "没触发就保持上一帧",
            "触发一次、发布一次、自动停止",
            "持续追加短数据块，不整帧启动/停止"]

# 触发源
SRC_CH1, SRC_CH2, SRC_ANY = 0, 1, 2
SRC_NAMES = ["CH1", "CH2", "任意"]

# 边沿
EDGE_RISE, EDGE_FALL = 0, 1

# 采集方式（步骤3/5 提到的三种）
MODE_NORMAL, MODE_PEAK, MODE_AVG = 0, 1, 2
MODE_NAMES = ["普通", "峰值", "平均"]

# 显示方式
DRAW_VECTOR, DRAW_ENVELOPE, DRAW_PERSIST = 0, 1, 2
DRAW_NAMES = ["矢量", "包络", "余辉"]

# V/格档位（标准示波器 1-2-5 序列，补上 2.5 让 AUTO 能打到 50%% 屏高）
VDIV_V = [0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0]
VDIV_NAMES = ["50mV", "100mV", "200mV", "250mV", "500mV", "1V", "2V", "2.5V", "5V"]


class TriggerModel:
    def __init__(self):
        self.src = SRC_CH1
        self.edge = EDGE_RISE
        self.level = 511          # LSB
        self.hys = 2              # LSB；None 表示自动
        self.auto_hys = True
        self.pretrigger = 0.5     # 0..1，触发点在帧内的比例
        self.holdoff_us = 0.0

    def commit_args(self):
        return {"src": self.src, "edge": self.edge, "level": self.level,
                "hys": self.hys, "pre": int(self.pretrigger * 4096)}


class AcqModel:
    def __init__(self):
        self.mode = ACQ_AUTO
        self.method = MODE_NORMAL
        self.depth = 4096
        self.avg_frames = 1

    def commit_args(self):
        return {"mode": self.mode, "method": self.method}


class DisplayModel:
    def __init__(self):
        self.draw = DRAW_ENVELOPE
        self.persist = 0
        self.show_measure = True
        self.show_cursor = False
        self.grid_v = 8
        self.grid_h = 10


class ScopeModel:
    """整个示波器的状态。UI 只碰这个对象。"""

    def __init__(self):
        self.ch = [ChannelCal(0), ChannelCal(1)]
        # ★ 默认两路都显示：实测多数场景信号接在 CH2，
        #   默认只显示 CH1 会让用户看到一条噪声平线。
        self.ch[0].enabled = True      # 默认两路都显示
        self.ch[1].enabled = True
        self.active = 0                             # 当前调节通道（0/1）
        self.trig = TriggerModel()
        self.acq = AcqModel()
        self.disp = DisplayModel()
        # ★ 默认时基改成 200us/格（一屏 2ms）。
        #   原来默认 1us/格（一屏 10us），而 1kHz 信号周期是 1ms ->
        #   一屏连 1% 个周期都不到，频率永远测不出来（读数是把信号自身
        #   的缓慢漂移当成了穿越，所以显示 4~8kHz 这种假值）。
        self.tb_index = 11
        self.tb = Timebase(self.tb_index)
        self.running = True
        self.single_armed = False
        self.hpos = 0.0                             # 水平位置（格）
        self.info = {}                              # 最近一帧的描述符
        self.m = [{}, {}]                           # 最近测量结果
        self.fps = 0.0
        self.lost = 0
        self._dirty = True

    # ---------------- 通道 / 显示 / 触发源 三者独立 ----------------
    def toggle_display(self, i):
        """只改显示，绝不动触发源、不动当前调节通道"""
        self.ch[i].enabled = not self.ch[i].enabled
        self._dirty = True

    def set_active(self, i):
        """只改当前调节通道，不动显示、不动触发源"""
        self.active = i

    def set_trig_src(self, s):
        """只改触发源"""
        self.trig.src = s
        self._dirty = True

    def any_displayed(self):
        return self.ch[0].enabled or self.ch[1].enabled

    # ---------------- 时基 ----------------
    def set_timebase(self, idx):
        self.tb_index = max(0, min(len(TIME_DIV) - 1, idx))
        self.tb.set(self.tb_index)
        self._dirty = True

    def tb_step(self, d):
        self.set_timebase(self.tb_index + d)

    # ---------------- 采集 ----------------
    def set_acq_mode(self, m):
        self.acq.mode = m & 3
        if self.acq.mode == ACQ_SINGLE:
            self.single_armed = True
        self._dirty = True

    def set_running(self, run):
        self.running = bool(run)

    def toggle_running(self):
        if self.acq.mode == ACQ_SINGLE:
            self.single_armed = True
            self.running = True
        else:
            self.running = not self.running

    # ---------------- 垂直 ----------------
    def vdiv_step(self, ch, d):
        """★ V/div 同时作用于【两个通道】。
        用户反馈："竖轴电压调了大小，但看到的波形没跟着变" ——
        原因是原来只改"当前调节通道"(m.active=CH1)，而信号在 CH2。
        现在改成两路一起改（auto_range 本来也是两路一起设，保持一致）。
        垂直位置(vpos)仍然按通道独立，因为那本来就是每路各自的中点偏移。
        """
        for c in self.ch:
            c.vdiv_idx = max(0, min(len(VDIV_V) - 1, c.vdiv_idx + d))

    def vpos_step(self, ch, d):
        self.ch[ch].vpos += d * 0.2      # 每次 0.2 格

    def vpos_reset(self, ch):
        self.ch[ch].vpos = 0.0

    # ---------------- 触发电平 ----------------
    def level_step(self, d):
        self.trig.level = max(0, min(SAMPLE_MAX, self.trig.level + d))
        self._dirty = True

    def level_reset(self):
        self.trig.level = 511
        self._dirty = True

    # ---------------- 水平位置 ----------------
    def hpos_step(self, d):
        self.hpos += d * 0.2             # 每次 0.2 格

    def hpos_reset(self):
        self.hpos = 0.0

    # ---------------- 自动量程（AUTO）----------------
    def auto_range(self, m, grid_r=8):
        """AUTO：一屏约 3 个周期、幅度约 50%、波形居中。

        ★ 关键：只有测量【已锁定】时才敢调。旧版不看 locked，
          拿噪声算出的假 vpp 去选量程，会选到极小的 V/div，
          波形直接顶出屏幕（这就是"太大"的根因）。
        """
        m = m or {}
        locked = bool(m.get("locked"))
        changed = []

        # ---------- 时间：一屏放 3 个周期 ----------
        f = m.get("freq") if locked else None
        if not f or f <= 0:
            # ★ 还测不到频率：多半是【时基太快，一屏装不下一个周期】。
            #   这时往更慢的档走一步去"找"信号，下一次调用（或下一次双击）
            #   就能测到频率，然后再按 3 个周期精调。
            if self.tb_index < len(TIME_DIV) - 1:
                self.set_timebase(self.tb_index + 1)
                changed.append("找信号->%s" % self.tb.label())
        if f and f > 0:
            want_tdiv = 2.5 / (f * 10.0)      # 一屏 2.5 个周期
            best, bd = self.tb_index, 1e18
            for i, tv in enumerate(TIME_DIV):
                d = abs(tv - want_tdiv) / want_tdiv
                if d < bd:
                    bd, best = d, i
            if best != self.tb_index:
                self.set_timebase(best)
                changed.append("时基->%s" % self.tb.label())

        # ---------- 垂直：幅度占 50%，并且留安全边距 ----------
        vpp = float(m.get("vpp", 0.0) or 0.0)
        if locked and vpp > 0.05:
            want = vpp / (grid_r * 0.5)          # 目标 50% 屏高
            best, bd = 4, 1e18
            for i, vd in enumerate(VDIV_V):
                d = abs(vd - want) / want
                if d < bd:
                    bd, best = d, i
            # 若该档会让波形超过 80% 屏高，就退到更大量程（宁可小一点）
            while best < len(VDIV_V) - 1 and vpp / VDIV_V[best] > grid_r * 0.80:
                best += 1
            for c in self.ch:
                c.vdiv_idx = best
            # 垂直位置：把信号中点摆到屏幕中心，并限幅在 ±3 格内
            mid = float(m.get("mid", 511))
            off = ((mid - 511.5) * V_FULL / SAMPLE_MAX) / VDIV_V[best]
            off = max(-3.0, min(3.0, off))
            for c in self.ch:
                c.vpos = off
            changed.append("量程->%s" % VDIV_NAMES[best])

        # ★ AUTO 要把水平位置归零：用户要求"每次重新按 AUTO 又能回到起始位置"
        if abs(self.hpos) > 1e-9:
            self.hpos = 0.0
            changed.append("水平位置->0")

        # ---------- 触发电平：摆到信号中点 ----------
        if locked:
            self.trig.level = int(max(0, min(SAMPLE_MAX, m.get("mid", 511))))

        self.hpos = 0.0
        self.running = True
        self._dirty = True
        return changed

    def auto_ready(self, m):
        """AUTO 是否可以执行：测量必须锁定。UI 用它决定是否提示"等信号稳定"。"""
        return bool((m or {}).get("locked"))

    def auto_hys(self):
        """hys = max(2, Vpp/32)：跟随信号幅度，小信号不会退化成超范围门限"""
        if not self.trig.auto_hys:
            return self.trig.hys
        pp = 0
        for m in self.m:
            if m:
                pp = max(pp, m.get("pp", 0))
        if pp <= 0:
            return 2
        return int(max(2, pp // 32))

    # ---------------- 原子提交 ----------------
    def commit(self, hw):
        """把当前配置一次写给 PL。UI 不该自己碰硬件寄存器。"""
        hw.configure(timebase=self.tb_index)
        hw.set_dec(self.tb.dec)
        hw.set_acqmode(self.acq.mode)
        hys = self.auto_hys()
        if self.trig.auto_hys:
            self.trig.hys = hys
        hw.set_hys(self.trig.hys)
        hw.set_trigcfg(self.trig.edge, self.acq.mode, self.trig.src)
        hw.configure(triglev=self.trig.level,
                     pre=int(self.trig.pretrigger * 4096))
        self._dirty = False

    def mark_dirty(self):
        self._dirty = True

    @property
    def dirty(self):
        return self._dirty
