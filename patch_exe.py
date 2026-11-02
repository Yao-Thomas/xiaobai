#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_exe.py —— PC 客户端（exe）优化：推理页 + 记住上次 IP

════════════════════════════════════════════════════════════════════
做两件事
════════════════════════════════════════════════════════════════════
① ★ 修「记住上次 IP」的 bug
   现状：扫描成功时只写了 conf["last_ip"]，
        而启动时 ChatApp 读的是 conf["host"]
        ⇒ 存了 A、读的是 B，"记了但没用"
   修：存 last_ip 的同时同步存 host；扫描时优先单播上次的 IP

② ★ 加「推理」页（原来只有聊天，没有推理）
   板子的 /infer 已经通了（实测 label=sine conf=1.0 elapsed=63ms），
   但没有界面能用它。加一页：
     · 选波形类型 / 频率 / 幅度 → 生成 4096 点 → 发给板子
     · 画波形预览
     · 显示 类别 / 置信度 / 耗时 / 引擎
     · 最近 10 次历史
   ★ 用"页签切换"而不是新开窗口 —— 不动现有聊天布局，风险最小

用法:
    python patch_exe.py --check
    python patch_exe.py
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "xb_chat.py")

# ── ① 修 last_ip ──
OLD_IP = '''                    self.conf["last_ip"] = d.get("ip", "")
                    save_conf(self.conf)'''
NEW_IP = '''                    # ★★★ 2026-10-03 修：原来只存 last_ip，
                    #   而启动时 ChatApp 读的是 conf["host"]
                    #   ⇒ 存了 A、读的是 B，"记住上次 IP" 形同虚设。
                    #   现在两个都写，并且只在本机没填过地址时才覆盖，
                    #   免得用户在设置里手填的地址被扫描结果冲掉。
                    _ip = d.get("ip", "")
                    if _ip:
                        self.conf["last_ip"] = _ip
                        if not self.conf.get("host"):
                            self.conf["host"] = _ip
                        save_conf(self.conf)'''

# ── ② 顶栏加页签按钮 ──
OLD_TOP = '''        self.lbl_temp = tk.Label(top, text="", bg=C["panel"], fg=C["dim"],
                                 font=(self.font, 9))
        self.lbl_temp.pack(side="right", padx=10)

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")'''
NEW_TOP = '''        self.lbl_temp = tk.Label(top, text="", bg=C["panel"], fg=C["dim"],
                                 font=(self.font, 9))
        self.lbl_temp.pack(side="right", padx=10)

        # ★★★ 页签：聊天 / 推理（2026-10-03）
        #   用按钮切换主体内容，不新开窗口 —— 布局改动最小。
        self._tab = "chat"
        self.btn_tab_chat = tk.Button(
            top, text="\\U0001f4ac 聊天", command=lambda: self.show_tab("chat"),
            bd=0, bg=C["panel"], fg=C["accent"], font=(self.font, 10, "bold"),
            activebackground=C["panel"], cursor="hand2")
        self.btn_tab_chat.pack(side="left", padx=(18, 4))
        self.btn_tab_infer = tk.Button(
            top, text="\\U0001f4ca 推理", command=lambda: self.show_tab("infer"),
            bd=0, bg=C["panel"], fg=C["dim"], font=(self.font, 10),
            activebackground=C["panel"], cursor="hand2")
        self.btn_tab_infer.pack(side="left", padx=4)

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")'''

# ── ③ 主体：right 区改成两个可切换的帧 ──
OLD_BODY = '''        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        self.msg = MessageArea(right)
        self.msg.on_speak_text = self.speak
        self.msg.pack(fill="both", expand=True)

        # ★ 输入区（含右下角的模型/模式切换）
        self._build_input(right)'''
NEW_BODY = '''        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)
        self.right = right

        # ★★★ 两个页面叠在同一个位置，用 pack/pack_forget 切换
        #   （tk 没有真正的 tab 控件，这是最省事又不破坏布局的做法）
        self.page_chat = tk.Frame(right, bg=C["bg"])
        self.page_infer = tk.Frame(right, bg=C["bg"])

        self.msg = MessageArea(self.page_chat)
        self.msg.on_speak_text = self.speak
        self.msg.pack(fill="both", expand=True)

        # ★ 输入区（含右下角的模型/模式切换）
        self._build_input(self.page_chat)

        # ★ 推理页
        self._build_infer(self.page_infer)

        self.page_chat.pack(fill="both", expand=True)'''

# ── ④ 加 show_tab + _build_infer + 推理逻辑（插在 _build_input 之前）──
ANCHOR_INFER = '''    def _build_input(self, parent):'''
ADD_INFER = '''    # ══════════════════════════════════════════════════════════════
    #  ★★★ 推理页（2026-10-03 加）
    # ══════════════════════════════════════════════════════════════
    # 板子的 /infer 早就通了（PL 加速器上的 CNN：cnn_conv_pool + cnn_fc），
    # 但 PC 客户端一直没有界面用它。这一页就是给它做的：
    #   选波形 → 生成 4096 点 → 发给板子 → 显示类别/置信度/耗时/引擎。
    # 8 个类别（板子 /infer/health 里报的）：
    #   sine / square / triangle / sawtooth / noise
    #   clipping / signal_loss / duty_abnormal
    # ══════════════════════════════════════════════════════════════
    WAVE_KINDS = [
        ("sine", "正弦"), ("square", "方波"), ("triangle", "三角"),
        ("sawtooth", "锯齿"), ("noise", "噪声"),
        ("clipping", "削顶"), ("signal_loss", "信号丢失"),
        ("duty_abnormal", "占空比异常"),
    ]
    WAVE_CN = dict(WAVE_KINDS)

    def show_tab(self, which):
        """切换 聊天 / 推理 页"""
        if which == self._tab:
            return
        self._tab = which
        if which == "chat":
            self.page_infer.pack_forget()
            self.page_chat.pack(fill="both", expand=True)
            self.btn_tab_chat.configure(fg=C["accent"],
                                        font=(self.font, 10, "bold"))
            self.btn_tab_infer.configure(fg=C["dim"],
                                         font=(self.font, 10))
        else:
            self.page_chat.pack_forget()
            self.page_infer.pack(fill="both", expand=True)
            self.btn_tab_infer.configure(fg=C["accent"],
                                         font=(self.font, 10, "bold"))
            self.btn_tab_chat.configure(fg=C["dim"],
                                        font=(self.font, 10))
            self.set_status("推理页：选波形 → 生成并推理")

    def _build_infer(self, parent):
        """推理页布局"""
        # ── 参数行 ──
        bar = tk.Frame(parent, bg=C["panel"])
        bar.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(bar, text="波形", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(12, 4))
        self.v_wave = tk.StringVar(value="sine")
        cb = ttk.Combobox(bar, textvariable=self.v_wave, width=10,
                          state="readonly",
                          values=[k for k, _ in self.WAVE_KINDS])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.infer_preview())

        tk.Label(bar, text="频率", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(16, 4))
        self.v_freq = tk.IntVar(value=40)
        tk.Spinbox(bar, from_=1, to=400, textvariable=self.v_freq, width=6,
                   command=self.infer_preview).pack(side="left")

        tk.Label(bar, text="幅度", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(16, 4))
        self.v_amp = tk.IntVar(value=120)
        tk.Spinbox(bar, from_=1, to=127, textvariable=self.v_amp, width=6,
                   command=self.infer_preview).pack(side="left")

        tk.Button(bar, text="★ 生成并推理", command=self.do_infer,
                  bd=0, bg=C["accent"], fg="#ffffff",
                  font=(self.font, 10, "bold"), cursor="hand2",
                  padx=14, pady=4).pack(side="left", padx=(20, 6))
        tk.Button(bar, text="随机换一个", command=self.infer_random,
                  bd=0, bg=C["side"], fg=C["text"],
                  font=(self.font, 10), cursor="hand2",
                  padx=10, pady=4).pack(side="left")

        # ── 波形预览 ──
        pv = tk.Frame(parent, bg=C["panel"],
                      highlightbackground=C["line"], highlightthickness=1)
        pv.pack(fill="x", padx=12, pady=6)
        self.cv_wave = tk.Canvas(pv, height=150, bg="#fbfcfe",
                                 highlightthickness=0)
        self.cv_wave.pack(fill="x", padx=8, pady=8)
        self.cv_wave.bind("<Configure>", lambda e: self.infer_preview())

        # ── 结果 ──
        res = tk.Frame(parent, bg=C["panel"],
                       highlightbackground=C["line"], highlightthickness=1)
        res.pack(fill="x", padx=12, pady=6)
        self.lbl_infer = tk.Label(res, text="还没推理过 —— 点上面「生成并推理」",
                                  bg=C["panel"], fg=C["dim"],
                                  font=(self.font, 12), anchor="w",
                                  justify="left")
        self.lbl_infer.pack(fill="x", padx=14, pady=12)

        # ── 历史 ──
        hp = tk.Frame(parent, bg=C["bg"])
        hp.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        tk.Label(hp, text="历史（最近 10 次）", bg=C["bg"], fg=C["dim"],
                 font=(self.font, 9)).pack(anchor="w")
        self.lst_hist = tk.Listbox(hp, bd=0, bg=C["panel"], fg=C["text"],
                                   font=("Consolas", 10), highlightthickness=1,
                                   highlightbackground=C["line"])
        self.lst_hist.pack(fill="both", expand=True, pady=(4, 0))
        self.infer_hist = []
        self.infer_preview()

    # ---------- 波形生成 ----------
    def gen_wave(self):
        """按当前参数生成 4096 点波形（和板子 /infer 的契约一致）"""
        import math as _m
        import random as _r
        kind = self.v_wave.get()
        f = max(1, int(self.v_freq.get() or 40))
        amp = max(1, min(127, int(self.v_amp.get() or 120)))
        N = 4096
        d = []
        for i in range(N):
            ph = (i * f / float(N)) % 1.0
            if kind == "sine":
                v = _m.sin(2 * _m.pi * ph)
            elif kind == "square":
                v = 1.0 if ph < 0.5 else -1.0
            elif kind == "triangle":
                v = 4 * abs(ph - 0.5) - 1
            elif kind == "sawtooth":
                v = 2 * ph - 1
            elif kind == "noise":
                v = _r.uniform(-1, 1)
            elif kind == "clipping":
                v = _m.sin(2 * _m.pi * ph) * 2.2      # 超幅 -> 削顶
                v = max(-1.0, min(1.0, v))
            elif kind == "signal_loss":
                v = 0.0 if i > N // 4 else _m.sin(2 * _m.pi * ph)
            elif kind == "duty_abnormal":
                v = 1.0 if ph < 0.82 else -1.0        # 占空比 82%
            else:
                v = _m.sin(2 * _m.pi * ph)
            d.append(int(127 + amp * v))
        return kind, [max(0, min(255, x)) for x in d]

    def infer_preview(self):
        """把当前波形画到预览 Canvas（不发网络请求）"""
        try:
            kind, d = self.gen_wave()
        except Exception:
            return
        cv = self.cv_wave
        cv.delete("all")
        w = max(200, cv.winfo_width())
        h = max(60, cv.winfo_height())
        mid = h // 2
        # 中线
        cv.create_line(0, mid, w, mid, fill="#e6e8ec")
        # 波形（4096 点太多，抽稀到宽度）
        step = max(1, len(d) // max(1, w))
        pts = []
        for x in range(0, w):
            i = min(len(d) - 1, x * step)
            y = mid - int((d[i] - 127) / 127.0 * (mid - 8))
            pts += [x, y]
        if len(pts) >= 4:
            cv.create_line(*pts, fill=C["accent"], width=2)
        cv.create_text(8, 12, anchor="w", fill=C["dim"],
                       font=(self.font, 9),
                       text="%s  %d Hz  幅度 %d（4096 点）"
                            % (self.WAVE_CN.get(kind, kind),
                               self.v_freq.get(), self.v_amp.get()))

    def infer_random(self):
        """随机换一个波形类型 + 参数"""
        import random as _r
        k = _r.choice([k for k, _ in self.WAVE_KINDS])
        self.v_wave.set(k)
        self.v_freq.set(_r.choice([10, 25, 40, 60, 100, 180]))
        self.v_amp.set(_r.choice([60, 90, 120, 127]))
        self.infer_preview()

    def do_infer(self):
        """生成波形 -> POST /infer -> 显示结果"""
        if self.busy:
            self.set_status("上一件事还没做完")
            return
        if not self.brd.host:
            self.set_status("还没填板子地址 —— 点右上角「设置」")
            return
        try:
            kind, d = self.gen_wave()
        except Exception as e:
            self.set_status("生成波形失败：%s" % e)
            return
        self.busy = True
        self.set_status("正在发给板子推理…")
        self.lbl_infer.configure(text="推理中…", fg=C["dim"],
                                 font=(self.font, 12))

        def work():
            import time as _t
            t0 = _t.time()
            try:
                r = self.brd.call("/infer", "POST",
                                  {"type": "waveform", "data": d,
                                   "hint": "raw", "api_key": self.brd.token},
                                  timeout=60)
                ms = int((_t.time() - t0) * 1000)
                self.q.put(("infer", {"kind": kind, "res": r, "ms": ms,
                                      "n": len(d)}))
            except Exception as e:
                self.q.put(("infer", {"kind": kind,
                                      "res": {"ok": False, "error": str(e)},
                                      "ms": 0, "n": len(d)}))
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _show_infer(self, p):
        """主线程显示推理结果"""
        self.busy = False
        r = p.get("res") or {}
        if not r.get("ok"):
            self.lbl_infer.configure(
                text="✗ 推理失败：%s" % (r.get("error") or "未知错误"),
                fg=C["rec"], font=(self.font, 11))
            self.set_status("推理失败")
            return
        lab = r.get("label") or "?"
        conf = r.get("confidence")
        el = r.get("elapsed_ms")
        eng = (r.get("detail") or {}).get("engine") or "?"
        txt = ("★ 类别：%s（%s）\\n"
               "   置信度：%s\\n"
               "   板上耗时：%s ms   （网络往返 %d ms）\\n"
               "   引擎：%s\\n"
               "   送入点数：%d"
               % (lab, self.WAVE_CN.get(lab, "?"),
                  ("%.1f%%" % (conf * 100)) if isinstance(conf, (int, float))
                  else str(conf),
                  el if el is not None else "?", p.get("ms", 0),
                  eng, p.get("n", 0)))
        # 判对没有？（我们自己知道发的是什么）
        exp = p.get("kind")
        hit = (lab == exp)
        self.lbl_infer.configure(
            text=txt + ("\\n\\n" + ("✓ 和生成时选的类别一致" if hit
                                  else "⚠ 生成的是 %s，板子判成 %s"
                                       % (self.WAVE_CN.get(exp, exp), lab))),
            fg=C["ok"] if hit else C["sys_fg"],
            font=(self.font, 11))
        import datetime as _dt
        line = ("%s  %-14s %-6s %5sms"
                % (_dt.datetime.now().strftime("%H:%M:%S"),
                   lab, ("%.0f%%" % (conf * 100))
                   if isinstance(conf, (int, float)) else "?",
                   el if el is not None else "?"))
        self.infer_hist.insert(0, line)
        self.lst_hist.insert(0, line)
        while self.lst_hist.size() > 10:
            self.lst_hist.delete("end")
        self.set_status("推理完成：%s" % lab)

    def _build_input(self, parent):'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 70)
    print(" PC 客户端优化：推理页 + 记住上次 IP")
    print("=" * 70)

    def sub(old, new, label):
        nonlocal src
        if old in src:
            src = src.replace(old, new, 1)
            print("   \u2713 %s" % label)
            return 1
        print("   \u2717 %s \u2014\u2014 锚点没找到" % label)
        return 0

    n = 0
    n += sub(OLD_IP, NEW_IP,
             "修「记住上次 IP」（原来存 last_ip 却读 host）")
    n += sub(OLD_TOP, NEW_TOP, "顶栏加「聊天 / 推理」页签按钮")
    n += sub(OLD_BODY, NEW_BODY, "主体改成两个可切换的页面")
    n += sub(ANCHOR_INFER, ADD_INFER, "加推理页（波形生成 + /infer + 历史）")

    # 把 infer 结果接进 _pump 的分发
    old_pump = '''                elif kind == "conn":'''
    new_pump = '''                elif kind == "infer":
                    self._show_infer(payload)
                elif kind == "conn":'''
    n += sub(old_pump, new_pump, "推理结果接进主线程分发（_pump）")

    print()
    print("   成功 %d / 5 处" % n)

    if a.check:
        print("\n （--check 模式，未写文件）")
        return 0
    if src == orig:
        print("\n \u2605 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 xb_chat.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
