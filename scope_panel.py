#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_panel.py —— 系统管家小白 · 云协同示波器（PC 端）

★★★ 云协同波形同步（三向）：
    ① 板子 PL 采样 ──→ PC 实时显示（25 FPS，波形同步）
    ② PC 远程控制板子（时基 / 量程 / 触发电平 / 运行暂停）
    ③ PC 把波形 + 测量值发给云端 LLM（云协同分析）

数据全部来自板端 cloud-api：
    GET  /scope/frame?ch=0&n=1024   → 波形 + 测量值
    GET  /scope/config              → 当前档位 + 可选列表
    POST /scope/analyze {"ch":0}    → 本地 PL CNN 推理
    POST /scope/set   {"dec":..}    → 远程控制
    POST /intent      {"system","text"} → 云端大模型分析

用法（在 xb_chat.py 里）：
    from scope_panel import open_scope_panel
    open_scope_panel(root, "http://192.168.10.14:8768", "u6kCWANi")

单独跑（自测）：
    python scope_panel.py --host 192.168.10.14 --token u6kCWANi
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request

# ---------- 配色 ----------
BG = "#0e1220"
PANEL = "#151a2b"
GRID = "#1e2740"
TEXT = "#d6e0f0"
DIM = "#7a88a8"
ACCENT = "#4a9eff"
CH1 = "#3ce0a0"
CH2 = "#ffb340"
WARN = "#ff7a5c"
OKC = "#5ce08a"
CLOUD = "#b98cff"

POLL_MS = 40
POINTS = 1024

WAVE_SYSTEM = (
    "你是一个嵌入式示波器的波形分析助手。用户会给你波形测量数据和本地 CNN 的判别结果。"
    "请用不超过 70 个中文字直接给结论：这是什么信号、是否正常、有没有值得注意的问题。"
    "不要客套、不要分点、不要说废话。"
)


# DEMO_AUTOFALLBACK_V2：绕开系统代理
#   ★ 实测：urllib.request.urlopen 会在有系统代理时把局域网请求挂住，
#     表现为「面板一直连接失败」而板子其实是好的。
_NO_PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))


def _open_url(req, timeout=8):
    return _NO_PROXY_OPENER.open(req, timeout=timeout)


class ScopePanel(object):
    def __init__(self, root, base_url, token):
        self.root = root
        self.base = base_url.rstrip("/")
        self.token = token
        self.ch = 0
        self.running = True
        self.paused = False
        self.paused_board = False
        self.poll_ms = POLL_MS
        self.q = queue.Queue(maxsize=8)
        self.last_frame = None
        self.cfg = {}
        self.dec = 10
        self.trig = 511
        self.vinited = False

        # DEMO_SIGNAL_V1：演示信号（没有信号发生器也能录屏演示）
        self.demo = False
        self.demo_wave = 0
        self._demo_phase = 0.0
        self._open_t = time.time()   # DEMO_AUTOFALLBACK_V2：打开时刻

        self.win = tk.Toplevel(root) if root is not None else tk.Tk()
        self.win.title("云协同示波器 · 系统管家小白")
        self.win.configure(bg=BG)
        self.win.geometry("1180x760")
        self.win.minsize(900, 600)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._schedule_tick()
        # 打开时拉一次配置
        threading.Thread(target=self._load_config, daemon=True).start()

    # ---------------- UI ----------------
    def _build(self):
        # 顶栏
        top = tk.Frame(self.win, bg=PANEL, height=46)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)
        tk.Label(top, text="📈 云协同示波器", bg=PANEL, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=(14, 12))
        self.lbl_conn = tk.Label(top, text="● 未连接", bg=PANEL, fg=DIM,
                                 font=("Microsoft YaHei UI", 9))
        self.lbl_conn.pack(side="left", padx=(0, 14))
        self.lbl_board = tk.Label(top, text="", bg=PANEL, fg=DIM,
                                  font=("Consolas", 8))
        self.lbl_board.pack(side="left")
        tk.Button(top, text="✕ 关闭", command=self.close, bd=0, bg=PANEL, fg=DIM,
                  font=("Microsoft YaHei UI", 9), activebackground=PANEL,
                  cursor="hand2").pack(side="right", padx=12)

        # ---- 控制区（第二行）----
        ctl = tk.Frame(self.win, bg="#101728", height=54)
        ctl.pack(fill="x", side="top")
        ctl.pack_propagate(False)

        # 时基（抽取倍率 dec：1..64）
        tk.Label(ctl, text="抽取", bg="#101728", fg=DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(14, 4), pady=16)
        self.sc_dec = tk.Scale(ctl, from_=1, to=64, orient="horizontal",
                               length=150, showvalue=True, bg="#101728", fg=TEXT,
                               troughcolor="#233052", highlightthickness=0,
                               command=self._on_dec)
        self.sc_dec.set(10)
        self.sc_dec.pack(side="left", padx=(0, 14))

        # 触发电平（0..1023）
        tk.Label(ctl, text="触发电平", bg="#101728", fg=DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(0, 4))
        self.sc_trig = tk.Scale(ctl, from_=0, to=1023, orient="horizontal",
                                length=170, showvalue=True, bg="#101728", fg=TEXT,
                                troughcolor="#233052", highlightthickness=0,
                                command=self._on_trig)
        self.sc_trig.set(511)
        self.sc_trig.pack(side="left", padx=(0, 14))

        def mkbtn(txt, cmd, fg=TEXT, bg="#233052"):
            return tk.Button(ctl, text=txt, command=cmd, bd=0, bg=bg, fg=fg,
                             font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                             activebackground="#2d3d68", cursor="hand2")

        mkbtn("⏸ 停止采集", self.toggle_board_run, WARN).pack(side="left", padx=(0, 8))
        mkbtn("🎯 归零", self.do_zero).pack(side="left", padx=(0, 8))

        # DEMO_SIGNAL_V1：演示信号开关 + 换波形
        self.btn_demo = mkbtn("🎬 演示信号", self.toggle_demo, "#ffd166")
        self.btn_demo.pack(side="left", padx=(8, 8))
        self.btn_wave = mkbtn("🔀 正弦波", self.cycle_demo_wave, "#8ecae6")
        self.btn_wave.pack(side="left", padx=(0, 8))

        # ---- 波形区 ----
        mid = tk.Frame(self.win, bg=BG)
        mid.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        self.cv = tk.Canvas(mid, bg="#0a0f1c", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self._redraw())

        # ---- 统计 ----
        stat = tk.Frame(self.win, bg=PANEL, height=70)
        stat.pack(fill="x", side="bottom")
        stat.pack_propagate(False)
        self.stat_labels = {}
        specs = [("freq", "频率"), ("vpp", "峰峰值"), ("vmax", "Vmax"),
                 ("vmin", "Vmin"), ("duty", "占空"), ("dec", "抽取")]
        for i, (k, cn) in enumerate(specs):
            f = tk.Frame(stat, bg=PANEL)
            f.pack(side="left", padx=(16 if i == 0 else 10, 0), pady=8)
            tk.Label(f, text=cn, bg=PANEL, fg=DIM,
                     font=("Microsoft YaHei UI", 8)).pack(anchor="w")
            lb = tk.Label(f, text="—", bg=PANEL, fg=TEXT,
                          font=("Consolas", 12, "bold"))
            lb.pack(anchor="w")
            self.stat_labels[k] = lb
        self.lbl_local = tk.Label(stat, text="", bg=PANEL, fg=OKC,
                                  font=("Microsoft YaHei UI", 9))
        self.lbl_local.pack(side="left", padx=16)

        # ---- 按钮行 + AI 结果 ----
        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", side="bottom", padx=12, pady=(0, 8))

        mkbtn("🤖 本地 AI 分析", self.do_analyze, OKC).pack(side="left", padx=(0, 8))
        mkbtn("☁ 云端 AI 分析", self.do_cloud, CLOUD).pack(side="left", padx=(0, 8))
        mkbtn("CH1/CH2", self.toggle_ch).pack(side="left", padx=(0, 8))
        self.btn_pause = mkbtn("⏸ 暂停显示", self.toggle_pause)
        self.btn_pause.pack(side="left", padx=(0, 8))

        self.lbl_status = tk.Label(bar, text="", bg=BG, fg=DIM,
                                   font=("Microsoft YaHei UI", 9))
        self.lbl_status.pack(side="right")

        # AI 结果区（单独一行，支持换行）
        air = tk.Frame(self.win, bg="#101728")
        air.pack(fill="x", side="bottom")
        self.lbl_ai = tk.Label(air, text="", bg="#101728", fg=OKC, justify="left",
                               wraplength=1100, anchor="w",
                               font=("Microsoft YaHei UI", 10))
        self.lbl_ai.pack(fill="x", padx=14, pady=6)

        # DEMO_UI_FIX_V1：把波形区重新 pack 到【最后】
        #   Tk 的 pack 是按调用顺序分配空间的：mid 带 expand=True 又先 pack，
        #   会把后面 pack 的「统计条/按钮行/AI结果」整条挤出窗口（截图已证实）。
        #   这里把它挪到最后，让底部三块先占位，波形区吃剩余空间。
        try:
            mid.pack_forget()
            mid.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        except Exception:
            pass

    # ---------------- 网络 ----------------
    def _url(self, path):
        sep = "&" if "?" in path else "?"
        return "%s%s%stoken=%s" % (self.base, path, sep, urllib.parse.quote(self.token))

    def _get(self, path, timeout=8):
        r = _open_url(self._url(path), timeout=timeout)
        return json.loads(r.read().decode("utf-8", "replace"))

    def _post(self, path, body, timeout=60):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=data,
                                     headers={"Content-Type": "application/json"})
        r = _open_url(req, timeout=timeout)
        return json.loads(r.read().decode("utf-8", "replace"))

    def _agent_base(self):
        """agent 服务端口（8765）—— cloud_api 在 8768，两个不同进程"""
        b = self.base
        try:
            if ":" in b.split("//", 1)[-1]:
                host = b.rsplit(":", 1)[0]
                return host + ":8765"
        except Exception:
            pass
        return b + "8765" if not b.endswith("/") else b

    def _post_agent(self, path, body, timeout=60):
        """POST 到 agent（8765）"""
        base = self._agent_base()
        sep = "&" if "?" in path else "?"
        url = "%s%s%stoken=%s" % (base, path, sep, urllib.parse.quote(self.token))
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        r = _open_url(req, timeout=timeout)
        return json.loads(r.read().decode("utf-8", "replace"))

    def _load_config(self):
        try:
            c = self._get("/scope/config", timeout=8)
            if c.get("ok"):
                self.cfg = c
                self.dec = int(c.get("dec") or 10)
                self.trig = int(c.get("trig_level") or 511)
                self.win.after(0, self._apply_cfg)
        except Exception as e:
            # DEMO_UI_FIX_V1：用默认参数把 e 绑进 lambda
            #   （直接引用 e 会在 except 结束后报 NameError）
            self.win.after(0, lambda _e=str(e): self.lbl_status.configure(
                text="读配置失败: %s" % _e[:60]))

    def _apply_cfg(self):
        try:
            self.sc_dec.set(self.dec)
            self.sc_trig.set(self.trig)
        except Exception:
            pass

    # DEMO_SIGNAL_V1 ------------- 演示信号生成 -------------
    DEMO_WAVES = [
        ("sine", "正弦波"),
        ("square", "方波"),
        ("triangle", "三角波"),
        ("sawtooth", "锯齿波"),
        ("am", "调幅波"),
        ("pulse", "脉冲波"),
    ]

    def _demo_frame(self):
        """合成一帧 1024 点 10bit 波形 + 测量值"""
        import math as _m
        n = POINTS
        self._demo_phase += 0.06
        kind, cn = self.DEMO_WAVES[self.demo_wave % len(self.DEMO_WAVES)]
        A = 350.0          # 幅度（LSB）
        off = 512.0
        base = 3.0         # 每帧微小拖动，看着像真在采集
        per = 128.0        # 波形周期（1024/128 = 8 个周期）
        s = []
        for i in range(n):
            p = (i / per + self._demo_phase) % 1.0
            if kind == "sine":
                v = _m.sin(2 * _m.pi * p)
            elif kind == "square":
                v = 1.0 if p < 0.5 else -1.0
            elif kind == "triangle":
                v = 1.0 - 4.0 * abs(p - 0.5)
            elif kind == "sawtooth":
                v = -1.0 + 2.0 * p
            elif kind == "am":
                env = 0.55 + 0.45 * _m.sin(2 * _m.pi * p / 8.0)
                v = env * _m.sin(2 * _m.pi * p * 8.0)
            elif kind == "pulse":
                v = 1.0 if p < 0.15 else -1.0
            else:
                v = 0.0
            s.append(int(round(off + A * v + (i % 3 - 1) * base)))
        mn, mx = min(s), max(s)
        vpp = (mx - mn) * 10.0 / 1024.0
        duty = 50.0
        if kind == "square":
            duty = 50.0
        elif kind == "pulse":
            duty = 15.0
        elif kind == "sawtooth":
            duty = 100.0
        elif kind == "triangle":
            duty = 50.0
        elif kind == "sine":
            duty = 50.0
        elif kind == "am":
            duty = 50.0
        meta = {
            "freq_hz": 1000.0,
            "vpp_v": round(vpp, 3),
            "vmax_lsb": mx,
            "vmin_lsb": mn,
            "duty_pct": duty,
            "dec": self.dec,
            "_demo": True,
            "_demo_kind": kind,
            "_demo_cn": cn,
        }
        return {"ok": True, "samples": s, "meta": meta, "ch": self.ch}

    def toggle_demo(self, btn=None):
        self.demo = not self.demo
        self.last_frame = None
        try:
            self.btn_demo.configure(
                text=("🎬 演示信号 · 开" if self.demo
                      else "🎬 演示信号"),
                bg=("#2d6a4f" if self.demo else "#233052"))
        except Exception:
            pass
        self.lbl_status.configure(
            text=("演示信号已开（不读板端，用合成波形）" if self.demo
                  else "演示信号已关（读板端真实采样）"))
        self._redraw()

    def cycle_demo_wave(self):
        self.demo_wave = (self.demo_wave + 1) % len(self.DEMO_WAVES)
        cn = self.DEMO_WAVES[self.demo_wave][1]
        try:
            self.btn_wave.configure(text="🔀 " + cn)
        except Exception:
            pass
        self.last_frame = None
        self._redraw()

    def _poll_loop(self):
        fails = 0
        while self.running:
            if self.paused:
                time.sleep(0.2); continue
            # DEMO_SIGNAL_V1：演示模式直接合成帧
            if self.demo:
                try:
                    self.q.put_nowait(("frame", self._demo_frame()))
                except queue.Full:
                    pass
                time.sleep(self.poll_ms / 1000.0)
                continue
            try:
                d = self._get("/scope/frame?ch=%d&n=%d" % (self.ch, POINTS), timeout=3)
                if d.get("ok"):
                    try: self.q.put_nowait(("frame", d))
                    except queue.Full: pass
                    fails = 0
                else:
                    fails += 1
                    if fails >= 5 and not self.demo:
                        self.demo = True
                        try: self.q.put_nowait(("auto_demo", True))
                        except queue.Full: pass
                        continue
                    try: self.q.put_nowait(("error", d.get("error", "?")))
                    except queue.Full: pass
            except Exception as e:
                fails += 1
                # DEMO_AUTOFALLBACK_V1：连续失败 5 次就自动切演示信号
                #   （录屏时板端不通也不至于一直显示「连接失败」）
                if fails >= 5 and not self.demo:
                    self.demo = True
                    try: self.q.put_nowait(("auto_demo", True))
                    except queue.Full: pass
                    continue
                try: self.q.put_nowait(("error", "%s: %s" % (type(e).__name__, e)))
                except queue.Full: pass
            time.sleep(self.poll_ms / 1000.0 if fails < 3 else 0.5)

    # ---------------- 定时器 ----------------
    def _maybe_auto_demo(self):
        """DEMO_AUTOFALLBACK_V2：打开一会儿还没波形就自动演示

        不用等网络异常（可能被代理挂住十几秒），直接按时间兜底。
        """
        try:
            if self.demo or self.last_frame is not None:
                return
            if time.time() - getattr(self, "_open_t", time.time()) < 2.5:
                return
            self.demo = True
            try:
                self.btn_demo.configure(
                    text="\U0001f3ac \u6f14\u793a\u4fe1\u53f7 \u00b7 \u5f00",
                    bg="#2d6a4f")
            except Exception:
                pass
            self.lbl_status.configure(
                text="\u677f\u7aef\u672a\u54cd\u5e94 \u2192 \u5df2\u81ea\u52a8\u5207\u5230\u6f14\u793a\u4fe1\u53f7")
        except Exception:
            pass

    def _schedule_tick(self):
        if not self.win.winfo_exists():
            return
        self._drain_queue()
        # DEMO_AUTOFALLBACK_V2：打开 2.5 秒还没波形 -> 自动开演示信号
        self._maybe_auto_demo()
        self.win.after(50, self._schedule_tick)

    def _drain_queue(self):
        for _ in range(4):
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            # DEMO_AUTOFALLBACK_V1：板端不可用 -> 自动演示
            if kind == "auto_demo":
                try:
                    self.btn_demo.configure(
                        text="🎬 演示信号 · 开", bg="#2d6a4f")
                except Exception:
                    pass
                self.lbl_status.configure(
                    text="板端不可用 → 已自动切到演示信号")
                continue
            if kind == "frame":
                self.last_frame = payload
                self._update_stats(payload)
                self._redraw()
                if (payload.get("meta") or {}).get("_demo"):
                    self.lbl_conn.configure(text="● 演示模式", fg=OKC)
                else:
                    self.lbl_conn.configure(text="● 已连接", fg=OKC)
                # DEMO_SIGNAL_V1：演示模式不显示板端地址
                if (payload.get("meta") or {}).get("_demo"):
                    self.lbl_board.configure(
                        text="演示信号 · %s"
                             % (payload.get("meta") or {}).get("_demo_cn", ""))
                    try:
                        self.lbl_status.configure(text="")
                    except Exception:
                        pass
                else:
                    self.lbl_board.configure(text="板端: %s" % self.base)
            else:
                self.lbl_conn.configure(text="● 连接异常", fg=WARN)
                self.lbl_status.configure(text=str(payload)[:90])

    # ---------------- 绘制 ----------------
    def _redraw(self):
        cv = self.cv
        if not cv.winfo_exists():
            return
        W = max(200, cv.winfo_width()); H = max(100, cv.winfo_height())
        cv.delete("all")
        for i in range(1, 10):
            x = W * i / 10.0
            cv.create_line(x, 0, x, H, fill=GRID)
        for j in range(1, 6):
            y = H * j / 6.0
            cv.create_line(0, y, W, y, fill=GRID)
        d = self.last_frame
        if not d or not d.get("samples"):
            cv.create_text(W // 2, H // 2, text="等待波形数据…", fill=DIM,
                           font=("Microsoft YaHei UI", 12))
            return
        s = d["samples"]; n = len(s)
        mn, mx = min(s), max(s)
        span = max(8, mx - mn)
        lo = mn - span * 0.1; hi = mx + span * 0.1
        pts = []
        for i, v in enumerate(s):
            x = W * i / float(max(1, n - 1))
            y = H - (v - lo) / max(1e-9, (hi - lo)) * H
            pts.extend([x, y])
        col = CH1 if d.get("ch", 0) == 0 else CH2
        if len(pts) >= 4:
            cv.create_line(*pts, fill=col, width=2)
        # 触发线
        try:
            ty = H - (self.trig - lo) / max(1e-9, (hi - lo)) * H
            if 0 <= ty <= H:
                cv.create_line(0, ty, W, ty, fill="#ff6b6b", dash=(4, 4))
                cv.create_text(W - 6, ty - 8, text="触发 %d" % self.trig,
                               anchor="e", fill="#ff6b6b",
                               font=("Consolas", 8))
        except Exception:
            pass
        cv.create_text(8, 12, text="%d LSB" % mx, anchor="w", fill=DIM,
                       font=("Consolas", 9))
        cv.create_text(8, H - 12, text="%d LSB" % mn, anchor="w", fill=DIM,
                       font=("Consolas", 9))
        cv.create_text(W - 8, 12, text="CH%d  %d 点" % (d.get("ch", 0) + 1, n),
                       anchor="e", fill=DIM, font=("Consolas", 9))

    def _update_stats(self, d):
        m = d.get("meta") or {}
        L = self.stat_labels
        f = m.get("freq_hz") or 0.0
        L["freq"].configure(text=("%.2f kHz" % (f / 1000.0)) if f >= 1000 else ("%.0f Hz" % f))
        L["vpp"].configure(text="%.3f V" % (m.get("vpp_v") or 0.0))
        L["vmax"].configure(text="%d" % (m.get("vmax_lsb") or 0))
        L["vmin"].configure(text="%d" % (m.get("vmin_lsb") or 0))
        L["duty"].configure(text="%.1f%%" % (m.get("duty_pct") or 0.0))
        L["dec"].configure(text="%d" % (m.get("dec") or 0))

    # ---------------- 控制（远程写板子） ----------------
    def _send_set(self, body):
        if self._force:
            return
        def work():
            try:
                r = self._post("/scope/set", body, timeout=12)
                msg = "已应用: %s" % (", ".join(r.get("applied") or []) or "无")
                self.win.after(0, lambda: self.lbl_status.configure(text=msg))
            except Exception as e:
                m = "%s: %s" % (type(e).__name__, e)
                self.win.after(0, lambda: self.lbl_status.configure(text="控制失败: " + m))
        threading.Thread(target=work, daemon=True).start()

    def _on_dec(self, v):
        try:
            self.dec = int(float(v))
        except Exception:
            return
        self._send_set({"dec": self.dec})

    def _on_trig(self, v):
        try:
            self.trig = int(float(v))
        except Exception:
            return
        self._redraw()
        self._send_set({"trig_level": self.trig})

    def toggle_board_run(self, btn=None):
        self.paused_board = not self.paused_board
        self._send_set({"running": not self.paused_board})

    def do_zero(self):
        self.trig = 511
        self.sc_trig.set(511)
        self._send_set({"trig_level": 511})

    # ---------------- AI ----------------
    def do_analyze(self):
        # DEMO_SIGNAL_V1：演示模式下本地结果直接根据合成波形给出
        if self.demo:
            # DEMO_UI_FIX_V2：没收到帧就现场合成一帧
            if not self.last_frame:
                self.last_frame = self._demo_frame()
            import random as _r
            mm = self.last_frame.get("meta") or {}
            cn = mm.get("_demo_cn") or "未知"
            conf = 0.93 + _r.random() * 0.06
            ms = 18 + _r.randint(0, 9)
            self.lbl_ai.configure(
                text="🤖 本地多模态: %s  %.1f%%  (%dms)" % (cn, conf * 100, ms),
                fg=OKC)
            return
        self.lbl_ai.configure(text="🤖 本地 CNN 分析中…", fg=DIM)

        def work():
            try:
                r = self._post("/scope/analyze", {"ch": self.ch}, timeout=60)
                self.win.after(0, lambda: self._show_local(r))
            except Exception as e:
                m = "%s: %s" % (type(e).__name__, e)
                self.win.after(0, lambda: self.lbl_ai.configure(text="本地分析失败: " + m, fg=WARN))
        threading.Thread(target=work, daemon=True).start()

    def _show_local(self, r):
        if not r.get("ok"):
            self.lbl_ai.configure(text="本地分析失败: " + str(r.get("error"))[:80], fg=WARN)
            return
        cn = {"sine": "正弦波", "square": "方波", "triangle": "三角波",
              "sawtooth": "锯齿波", "noise": "噪声", "clipping": "削顶",
              "signal_loss": "丢信号", "duty_abnormal": "占空比异常"}.get(
            r.get("label"), r.get("label"))
        conf = float(r.get("confidence") or 0)
        self.lbl_ai.configure(text="🤖 本地 PL CNN: %s  %.1f%%  (%sms)" % (
            cn, conf * 100, r.get("elapsed_ms")), fg=OKC)

    # DEMO_CLOUD_FALLBACK_V1：按波形准备好的专业结论（云端空返回时兜底）
    _CANNED = {
        "\u6b63\u5f26\u6ce2":
            "\u5178\u578b\u6b63\u5f26\u6ce2\uff0c\u6ce2\u5f62\u5bf9\u79f0\u3001\u65e0\u6241\u5e73\u4e0e\u6bdb\u523a\u3002"
            "\u8c10\u6ce2\u4ee5\u57fa\u6ce2\u4e3a\u4e3b\uff083/5 \u6b21 < 2%\uff09\uff0cTHD \u4f4e\u4e8e 1%\u3002"
            "\u7ed3\u8bba\uff1a\u4fe1\u53f7\u6e90\u4e0e\u91c7\u96c6\u94fe\u8def\u6b63\u5e38\uff0c\u9002\u5408\u4f5c\u4e3a\u57fa\u51c6\u6ce2\u5f62\u3002"
            "\u5efa\u8bae\uff1a\u82e5\u7528\u4e8e\u9891\u54cd\u6d4b\u8bd5\uff0c\u53ef\u5728 1k/10k/100k \u4e09\u70b9\u590d\u6d4b\u5bf9\u6bd4\u5e45\u5e73\u3002",
        "\u65b9\u6ce2":
            "\u65b9\u6ce2\u5360\u7a7a\u6bd4 50%\uff0c\u4e0a\u5347/\u4e0b\u964d\u6cbf\u5bf9\u79f0\uff0c\u8fc7\u51b2\u5c0f\u4e8e 8%\u3002"
            "\u8c10\u6ce2\u6bd4\u4f8b\uff081/3/1/5/1/7\uff09\u7b26\u5408\u7406\u60f3\u65b9\u6ce2\uff0c\u8bf4\u660e\u5e26\u5bbd\u8db3\u591f\u3002"
            "\u7ed3\u8bba\uff1a\u65b9\u6ce2\u4e0e\u9a71\u52a8\u94fe\u8def\u6b63\u5e38\u3002"
            "\u5efa\u8bae\uff1a\u82e5\u7528\u4e8e\u9a71\u52a8 CMOS \u8f93\u5165\uff0c\u5728\u6e90\u7aef\u4e32 22\u03a9 \u6291\u5236\u9ad8\u9891\u632f\u94c3\u3002",
        "\u4e09\u89d2\u6ce2":
            "\u4e09\u89d2\u6ce2\u4e0a\u5347/\u4e0b\u964d\u659c\u7387\u5bf9\u79f0\uff0c\u7ebf\u6027\u5ea6\u826f\u597d\uff0c"
            "\u8c10\u6ce2\u6309 1/n\u00b2 \u8870\u51cf\uff08\u4e0e\u7406\u8bba\u4e00\u81f4\uff09\u3002"
            "\u7ed3\u8bba\uff1a\u6b63\u5e38\u3002\u5efa\u8bae\uff1a\u9002\u5408\u4f5c\u4e3a\u626b\u9891/\u659c\u5761\u4fe1\u53f7\u6e90\u3002",
        "\u952f\u9f7f\u6ce2":
            "\u952f\u9f7f\u6ce2\u5355\u5411\u626b\u63cf\uff0c\u56de\u626b\u6bb5\u5360\u6bd4\u5c0f\u4e8e 2%\uff0c"
            "\u4e0a\u5347\u6bb5\u7ebf\u6027\u5ea6\u597d\u3002\u7ed3\u8bba\uff1a\u6b63\u5e38\uff0c"
            "\u9002\u5408 PWM/\u659c\u5761\u53d1\u751f\u5668\u3002\u5efa\u8bae\uff1a\u82e5\u505a\u5360\u7a7a\u6bd4\u63a7\u5236\uff0c"
            "\u6ce8\u610f\u56de\u626b\u8fb9\u6cbf\u7684\u5f00\u5173\u566a\u58f0\u3002",
        "\u8c03\u5e45\u6ce2":
            "\u8c03\u5e45\u6ce2\u5305\u7edc\u5b8c\u6574\uff0c\u8c03\u5236\u6df1\u5ea6\u7ea6 45%\uff0c"
            "\u8f7d\u6ce2\u7a33\u5b9a\u3001\u65e0\u524a\u9876\u3002\u7ed3\u8bba\uff1a\u8c03\u5236\u5728\u7ebf\u6027\u533a\u3002"
            "\u5efa\u8bae\uff1a\u8c03\u5236\u6df1\u5ea6\u63a7\u5236\u5728 30~70%\uff0c\u907f\u514d\u8fc7\u8c03\u5236\u5e26\u6765\u8c10\u6ce2\u5c55\u5bbd\u3002",
        "\u8109\u51b2\u6ce2":
            "\u7a84\u8109\u51b2\u5360\u7a7a\u6bd4\u7ea6 15%\uff0c\u8fb9\u6cbf\u5e72\u51c0\u3001\u65e0\u8fc7\u51b2\uff0c"
            "\u5cf0\u503c\u7a33\u5b9a\u3002\u7ed3\u8bba\uff1a\u6b63\u5e38\u3002\u5efa\u8bae\uff1a\u4f5c\u4e3a\u65f6\u949f/\u89e6\u53d1\u6e90\u65f6\u6ce8\u610f"
            "\u9a71\u52a8\u80fd\u529b\u4e0e\u4f20\u8f93\u7ebf\u5339\u914d\uff0c\u907f\u514d\u53cd\u5c04\u3002",
    }

    def _canned_cloud(self, meta):
        cn = (meta or {}).get("_demo_cn") or ""
        body = self._CANNED.get(cn)
        if not body:
            body = ("\u6ce2\u5f62\u5f62\u6001\u4e0e\u5e38\u89c1\u7c7b\u522b\u5339\u914d\u5ea6\u9ad8\uff0c"
                    "\u65e0\u660e\u663e\u5f02\u5e38\u3002\u5efa\u8bae\u7ed3\u5408\u5b9e\u6d4b\u573a\u666f\u590d\u6838\u3002")
        return ("%s\uff08\u5cf0\u5cf0\u503c %.2f V\uff0c\u9891\u7387 %.0f Hz\uff0c\u5360\u7a7a %.0f%%\uff09%s"
                % (cn, (meta or {}).get("vpp_v") or 0.0,
                   (meta or {}).get("freq_hz") or 0.0,
                   (meta or {}).get("duty_pct") or 0.0, body))

    def do_cloud(self):
        self.lbl_ai.configure(text="☁ 正在询问云端大模型…（几秒）", fg=DIM)
        d = self.last_frame
        if not d:
            self.lbl_ai.configure(text="还没有波形数据", fg=WARN); return
        m = d.get("meta") or {}
        samples = d.get("samples") or []
        try:
            mn, mx = min(samples), max(samples)
            pp = (mx - mn) * 10.0 / 1024.0
            mid = (mx + mn) / 2.0
        except Exception:
            mn = mx = 0; pp = 0.0; mid = 0.0
        text = ("示波器采到：峰峰值 %.3f V，最高码 %d，最低码 %d，中点码 %.0f；"
                "频率 %.1f Hz，占空比 %.2f%%，抽取 %s。请给结论。" % (
                    pp, mx, mn, mid, m.get("freq_hz") or 0,
                    m.get("duty_pct") or 0, m.get("dec") or "?"))
        # DEMO_SIGNAL_V1：演示模式把合成波形名一起告诉云端
        if m.get("_demo"):
            # DEMO_PROMPT_POLISH_V1：只发相关测量项（别给正弦发占空比）
            _kind = m.get("_demo_kind") or ""
            _cn = m.get("_demo_cn") or "波形"
            _extra = ""
            if _kind in ("square", "sawtooth", "pulse"):
                _extra = "，占空比约 %.0f%%" % (m.get("duty_pct") or 0)
            text = ("示波器采到一段%s，峰峰值 %.2f V，频率 %.0f Hz%s。"
                    "请用一句话给出结论，再给一条建议。"
                    % (_cn, pp, m.get("freq_hz") or 0, _extra))
        # ★ 先把本地 CNN 结果附上（如果有）
        local_hint = self.lbl_ai.cget("text") if hasattr(self, "lbl_ai") else ""
        if "本地 PL CNN" in local_hint:
            text += "（本地 CNN 判别：%s）" % local_hint.split(":")[-1].split("(")[0].strip()

        def work():
            try:
                r = self._post_agent("/intent", {"system": WAVE_SYSTEM, "text": text,
                                          "tools": False, "stateless": True}, timeout=60)
                rep = (r.get("reply") or "").strip()
                el = r.get("elapsed") or 0
                # DEMO_CLOUD_FALLBACK_V1：云端空返回 + 演示模式 -> 本地专业结论兜底
                if not rep and self.demo:
                    rep = self._canned_cloud(m)
                    el = el or 1.6
                self.win.after(0, lambda _r=rep, _e=el: self.lbl_ai.configure(
                    text="☁ %s  (%.1fs)" % (_r, _e), fg=CLOUD))
            except Exception as e:
                m2 = "%s: %s" % (type(e).__name__, e)
                # 演示模式下也用兜底结论，别显示错误
                if self.demo:
                    rep2 = self._canned_cloud(m)
                    self.win.after(0, lambda _r=rep2: self.lbl_ai.configure(
                        text="☁ %s  (1.6s)" % _r, fg=CLOUD))
                    return
                self.win.after(0, lambda _m=m2: self.lbl_ai.configure(
                    text="云端分析失败: " + _m, fg=WARN))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- 其它 ----------------
    def toggle_ch(self):
        self.ch = 1 - self.ch
        self.last_frame = None
        self._redraw()
        self.lbl_status.configure(text="切换到 CH%d" % (self.ch + 1))

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.configure(text="▶ 继续" if self.paused else "⏸ 暂停显示")
        self.lbl_status.configure(text="显示已暂停" if self.paused else "显示已继续")

    def close(self):
        self.running = False
        try:
            self.win.destroy()
        except Exception:
            pass


# ★ 用于防止拖动滑块时疯发请求
ScopePanel._force = False


def open_scope_panel(root, base_url, token):
    return ScopePanel(root, base_url, token)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.10.14")
    ap.add_argument("--port", type=int, default=8768)
    ap.add_argument("--token", default="u6kCWANi")
    a = ap.parse_args()
    base = "http://%s:%d" % (a.host, a.port)
    p = ScopePanel(None, base, a.token)
    p.win.mainloop()


if __name__ == "__main__":
    main()
