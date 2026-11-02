#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_agent.py —— 系统管家小白（板载 Agent 桌面入口）

* 打字提问 -> 板载 Agent 服务 (127.0.0.1:8765 /voice) -> 回复
* 「朗读」用百度 TTS 合成后交给板载音频服务从喇叭放出来
* 「听」开麦克风录几秒 -> 百度 ASR -> 填进输入框
* 「自检」放音同时录音，验证喇叭和麦克风

★ 所有网络/录音都在后台线程里跑，主循环绝不阻塞 ——
  这是之前"点了没反应"的教训（网络超时把界面卡死）。
"""
import os
import json
import time
import queue
import threading
import urllib.request

from fbui import header, back_hit, btn, hit, MiniKeyboard

AGENT_URL = os.environ.get("AGENT_SVC", "http://127.0.0.1:8765")
AUDIO_URL = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")

LOG_RECT = [36, 108, 988, 346]
IN_RECT = [36, 352, 988, 388]        # 输入框（已上屏的文字）
CAND_RECT = [36, 392, 988, 430]      # ★ 候选栏 / 常用指令栏
BTN_Y = 70
BTN_H = 32
KB_Y = 436                           # 键盘（压缩过，给候选栏腾地方）
KB_KH = 27
KB_GAP = 3

# 常用指令：拼音缓冲为空时显示在候选栏上，点一下就发
QUICK = ["现在几点", "今天天气", "播放音乐", "你好", "介绍一下你自己",
         "停止播放", "看一看时间"]


def _post(url, obj, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class AgentApp(object):
    def __init__(self):
        # ★ 消息改成 (角色, 文字)：user=我说的 / bot=小白说的 / sys=系统提示
        self.msgs = [("bot", "我是系统管家小白 —— 这块板子的系统管家。"),
                     ("sys", "打字后按回车问我；也可以点「听」用说的。")]
        self.lines = ["我是系统管家小白 —— 这块板子的系统管家。",
                      "打字后按回车问我；也可以点「听」用说的。"]
        self.cur = ""
        self.kb = MiniKeyboard(y0=KB_Y, key_w=76, key_h=KB_KH, gap=KB_GAP)
        # ★ 本地中文输入法（不联网）。数据表由 PC 上的 build_ime_data.py 生成。
        self.ime = None
        try:
            from ime_cn import IME
            self.ime = IME()
        except Exception as e:
            print("IME 加载失败:", e, flush=True)
        self.py = ""            # 拼音缓冲（还没上屏的字母）
        self.cands = []         # 当前候选 [(文本, kind)]
        self.pinyin = True      # 拼音 / 英文
        self.quick = 0          # 常用指令滚动位置
        # ★ 待批准的危险动作（来自 Agent 权限层 /pending）
        self.pending = []
        self._pend_t = 0.0
        # ★ 屏幕上**实际画出来**的候选栏/批准栏条目。
        #   点击只跟这份对，避免"画的"和"点的"不是同一份。
        self.bar_rendered = []
        self.q = queue.Queue()
        self.busy = ""
        self.last_reply = ""
        self.out("正在检查 Agent / 音频服务 ...")
        self._probe()

    # ---- 日志 ----
    def out(self, s):
        """加一条消息。按前缀判断角色（保持旧调用不变）。"""
        for raw in str(s).split("\n"):
            ln = raw.strip()
            if not ln:
                continue
            if ln.startswith("我>"):
                self.msgs.append(("user", ln[2:].strip()))
            elif ln.startswith("小白>"):
                self.msgs.append(("bot", ln[3:].strip()))
            else:
                self.msgs.append(("sys", ln))
            self.lines.append(ln[:118])
        self.lines = self.lines[-300:]
        self.msgs = self.msgs[-200:]

    # ══════════════════════════════════════════════════════════
    #  气泡排版（参考 Harness / 现代聊天界面）
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def _wrap(scr, text, size, maxw):
        """中文自动换行。中文没空格，必须逐字量宽。"""
        out, cur = [], ""
        for ch in text:
            if ch == "\n":
                out.append(cur)
                cur = ""
                continue
            t = cur + ch
            if cur and scr.tw(t, size, cn=True) > maxw:
                out.append(cur)
                cur = ch
            else:
                cur = t
        if cur:
            out.append(cur)
        return out or [""]

    def layout(self, scr):
        """从**底部往上**排版所有气泡，返回 [(role, lines, rect, h)]。

        底部优先 -> 最新消息永远可见，旧的自动被挤出去。
        """
        x0, y0, x1, y1 = LOG_RECT
        pad = 10
        avail_w = (x1 - x0) - 2 * pad
        maxw = int(avail_w * 0.62)          # 气泡最大宽 62%，像手机聊天
        size = 17
        lh = 22                              # 行高
        items = []
        ybot = y1 - pad
        for role, text in reversed(self.msgs):
            if role == "sys":
                w = min(avail_w, scr.tw(text, 14, cn=True) + 16)
                lw = maxw if False else avail_w
                lines = self._wrap(scr, text, 14, avail_w - 16)
                h = len(lines) * 19 + 8
                x = x0 + pad + (avail_w - w) // 2
                r = [x, ybot - h, x + w, ybot]
            elif role == "user":
                lines = self._wrap(scr, text, size, maxw - 24)
                w = max(scr.tw(x, size, cn=True) for x in lines) + 24
                h = len(lines) * lh + 18
                r = [x1 - pad - w, ybot - h, x1 - pad, ybot]
            else:                            # bot
                lines = self._wrap(scr, text, size, maxw - 46)
                w = max(scr.tw(x, size, cn=True) for x in lines) + 46
                h = len(lines) * lh + 18
                r = [x0 + pad, ybot - h, x0 + pad + w, ybot]
            if r[1] < y0 + 2:                # 超出上边界就停（更旧的看不见）
                break
            items.append((role, lines, r, h))
            ybot = r[1] - 8                  # 气泡间距
        items.reverse()
        return items

    def draw_bubbles(self, scr):
        """画消息气泡 + 头像 + 正在输入指示"""
        x0, y0, x1, y1 = LOG_RECT
        scr.rrect(LOG_RECT, 10, fill=(13, 15, 22), outline=(44, 52, 72))
        items = self.layout(scr)
        for role, lines, r, h in items:
            if role == "user":
                scr.rrect(r, 10, fill=(48, 96, 168))          # 蓝色：我说的
                tx, col = r[0] + 12, (240, 246, 255)
                for i, ln in enumerate(lines):
                    scr.text((tx, r[1] + 9 + i * 22), ln, 17, col, cn=True)
            elif role == "bot":
                scr.rrect(r, 10, fill=(30, 36, 50))           # 深灰：小白说的
                # 头像（圆形，左上角，和 Harness 一样有身份感）
                ax, ay, ar = r[0] + 20, r[1] + 20, 11
                scr.d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar],
                              fill=(74, 128, 210))
                scr.text((ax, ay), "白", 14, (255, 255, 255), anchor="mm",
                         cn=True)
                tx = r[0] + 40
                for i, ln in enumerate(lines):
                    scr.text((tx, r[1] + 9 + i * 22), ln, 17,
                             (226, 234, 248), cn=True)
            else:                                             # sys
                for i, ln in enumerate(lines):
                    scr.text((r[0] + 8, r[1] + 4 + i * 19), ln, 14,
                             (122, 138, 168), cn=True)

        # ---- 正在思考：三个跳动的点 ----
        if self.busy:
            import math as _m
            import time as _t
            bx, by = x0 + 40, y0 + 22
            h2 = 34
            scr.rrect([x0 + 10, y0 + 6, x0 + 96, y0 + 6 + h2], 10,
                      fill=(30, 36, 50))
            ax, ay, ar = x0 + 30, y0 + 23, 10
            scr.d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar],
                          fill=(74, 128, 210))
            scr.text((ax, ay), "白", 13, (255, 255, 255), anchor="mm", cn=True)
            ph = _t.time() * 4.0
            for k in range(3):
                rr = 3.0 + 1.8 * (1 + _m.sin(ph - k * 0.9)) / 2.0
                cx = x0 + 56 + k * 13
                scr.d.ellipse([cx - rr, ay - rr, cx + rr, ay + rr],
                              fill=(150, 180, 230))

    def _bg(self, name, fn):
        if self.busy:
            return False      # ★ 上一件事还没做完
        self.busy = name

        def wrap():
            try:
                self.q.put((name, fn()))
            except Exception as e:
                self.q.put((name, "错误: %s: %s" % (type(e).__name__, e)))
        threading.Thread(target=wrap, daemon=True).start()
        return True


    def _probe(self):
        def fn():
            out = []
            try:
                h = _get(AGENT_URL + "/health", timeout=5)
                out.append("Agent 服务: %s" % ("在线" if h.get("ok") is not False
                                              else h))
            except Exception as e:
                out.append("Agent 服务: 不在线（%s）" % e)
            try:
                h = _get(AUDIO_URL + "/health", timeout=5)
                out.append("音频服务: %s port=%s" % (h.get("name"), h.get("port")))
            except Exception:
                # ★ 不要把 Python 异常原文甩给用户（"urlopen error [Errno 111]"
                #   又长又丑）。音频服务被停掉时给一句人话。
                out.append("音频服务: 已停止（放音和录音都不可用）")
            return "\n".join(out)
        self._bg("probe", fn)

    def ask(self, text):
        def fn():
            d = _post(AGENT_URL + "/voice", {"text": text}, timeout=300)
            self.last_reply = d.get("reply") or "(空回复)"
            return "小白> " + self.last_reply + \
                   "\n      (%s 轮, %ss)" % (d.get("rounds"), d.get("elapsed"))
        self._bg("ask", fn)

    def say(self):
        if not self.last_reply:
            self.out("还没有可朗读的回复。")
            return
        txt = self.last_reply

        def fn():
            # 优先让板上 tts 模块做（它知道百度密钥在哪）
            import sys
            if "/home/zynq/agent" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            try:
                from agent import tts
                p, secs = tts.speak(txt[:300])
                return "已朗读 %.1f 秒" % secs
            except Exception as e:
                raise RuntimeError("朗读失败: %s: %s" % (type(e).__name__, e))
        self._bg("say", fn)

    def listen(self, secs=4.0):
        def fn():
            import sys
            if "/home/zynq" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            from agent import tts
            text, p = tts.listen(secs=secs)
            if text:
                self.cur = text
            return "听到: " + (text or "(没听清)") + "   [" + p + "]"
        self._bg("listen", fn)

    def voice(self, secs=4.0):
        """★ 完整语音闭环：麦克风 -> ASR -> Agent -> TTS -> 喇叭"""
        def fn():
            import sys
            if "/home/zynq" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            from agent.voice_loop import VoiceLoop
            lines = []
            v = VoiceLoop(verbose=False, on_state=lambda s: lines.append("状态: " + s))
            t, r = v.once(secs=secs)
            if r:
                self.last_reply = r
            out = "\n".join(lines + v.log)
            return out if out else "（没有有效语音输入）"
        self._bg("voice", fn)

    def selftest(self):
        def fn():
            d = _post(AUDIO_URL + "/selftest", {"freq": 1000, "secs": 1.2},
                      timeout=240)
            return "自检: %s\n  @%.0fHz 静音 %.1f -> 放音 %.1f (%.1f dB)" % (
                d.get("verdict"), d.get("freq", 1000), d.get("goe_quiet", 0),
                d.get("goe_tone", 0), d.get("ratio_db", 0))
        self._bg("selftest", fn)

    def pump(self):
        while True:
            try:
                name, res = self.q.get_nowait()
            except queue.Empty:
                break
            self.busy = ""
            self.out(res)

        # ★ 每 2 秒轮询一次待批准队列（直接 HTTP，很快）
        import time as _t
        if _t.time() - self._pend_t > 2.0:
            self._pend_t = _t.time()
            try:
                d = _get(AGENT_URL + "/pending", timeout=2)
                self.pending = d.get("pending") or []
            except Exception:
                pass

    def _approve(self, rid, ok):
        """同意 / 拒绝一个待批准动作"""
        def fn():
            try:
                d = _post(AGENT_URL + "/approve",
                          {"id": rid, "ok": ok}, timeout=10)
                self.pending = []
                if ok:
                    it = d.get("resolved") or {}
                    return ("已同意: %s  —— 5 分钟内同一条命令可直接执行"
                            % it.get("payload", rid))
                return "已拒绝: %s" % rid
            except Exception as e:
                return "操作失败: %s" % e
        self._bg("approve", fn)

    # ---- 拼音输入 ----
    def refresh_cands(self):
        """重算候选。缓冲为空 -> 用常用指令填满候选栏"""
        if not self.pinyin:
            self.cands = []
            return
        if self.py and self.ime and self.ime.ok:
            self.cands = self.ime.candidates(self.py, limit=8)
        else:
            self.cands = []

    def commit(self, text):
        """把候选/指令上屏，清掉拼音缓冲"""
        self.cur += text
        self.py = ""
        self.refresh_cands()

    def commit_first(self):
        """空格/回车：优先上屏第一个候选，没有候选就把字母原样上屏"""
        if self.py:
            if self.cands:
                self.commit(self.cands[0][0])
            else:
                self.cur += self.py
                self.py = ""
                self.refresh_cands()
            return True
        return False

    def bar_items(self, scr):
        """返回候选栏上要画的东西 [(文本, 动作, 矩形)]

        有拼音缓冲 -> 候选字/词；没有 -> 常用指令
        """
        items = []
        x = CAND_RECT[0] + 6
        y0, y1 = CAND_RECT[1] + 4, CAND_RECT[3] - 4
        h = y1 - y0

        # ★★ 优先级最高：有待批准的危险动作 -> 显示批准条
        if self.pending:
            it = self.pending[0]
            act = str(it.get("payload") or "")
            if len(act) > 42:
                act = act[:40] + "..."
            items.append(("[!] 同意? " + act, "none",
                          [x, y0, x + 500, y1]))
            x += 506
            items.append(("同意", "approve:%s:1" % it["id"],
                          [x, y0, x + 76, y1]))
            x += 80
            items.append(("拒绝", "approve:%s:0" % it["id"],
                          [x, y0, x + 76, y1]))
            x += 80
            if len(self.pending) > 1:
                items.append(("全部拒绝", "approve:all:0",
                              [x, y0, x + 104, y1]))
            return items

        # 左侧：模式切换
        mw = 66
        items.append(("拼音" if self.pinyin else "英文", "mode",
                      [x, y0, x + mw, y1]))
        x += mw + 6
        if self.py and self.cands:
            for i, (t, kind) in enumerate(self.cands):
                w = max(46, scr.tw(t, 20, cn=True) + 22)
                if x + w > CAND_RECT[2] - 8:
                    break
                # 第一个候选给个高亮边框提示"空格可上屏"
                items.append((t, "cand:%d" % i, [x, y0, x + w, y1]))
                x += w + 4
        elif not self.py:
            # 常用指令（点一下就发）
            for i, q in enumerate(QUICK):
                w = max(60, scr.tw(q, 16, cn=True) + 18)
                if x + w > CAND_RECT[2] - 8:
                    break
                items.append((q, "quick:%s" % q, [x, y0, x + w, y1]))
                x += w + 4
        return items

    # ---- 绘制 ----
    def buttons(self, scr):
        b = []
        x = 36
        for name, act in (("语音对话", "voice"), ("问", "ask"), ("朗读", "say"),
                          ("听 4 秒", "listen"), ("自检", "selftest"),
                          ("服务状态", "probe"), ("清屏", "clear")):
            w = scr.tw(name, 17, cn=True) + 26
            b.append((name, act, [x, BTN_Y, x + w, BTN_Y + BTN_H]))
            x += w + 8
        return b

    def draw(self, scr, btns):
        scr.clear((10, 12, 22))
        header(scr, "系统管家小白")
        for name, act, r in btns:
            on = (self.busy == act)
            btn(scr, r, name,
                fill=(150, 90, 40) if on else (52, 70, 120),
                size=17, cn=True, radius=8)
        if self.busy:
            scr.text((1000, BTN_Y + BTN_H // 2), "工作中:" + self.busy,
                     16, (250, 200, 120), anchor="rm", cn=True)

        self.draw_bubbles(scr)

        scr.rrect(IN_RECT, 8, fill=(20, 26, 44), outline=(70, 100, 160))
        shown = "> " + self.cur[-70:]
        if self.py:
            shown += "  [ " + self.py + " ]"
        scr.text((IN_RECT[0] + 10, (IN_RECT[1] + IN_RECT[3]) // 2),
                 shown + "_", 19, (230, 240, 255), anchor="lm", cn=True)

        # ★ 候选栏 / 常用指令栏
        scr.rrect(CAND_RECT, 8, fill=(16, 20, 32), outline=(52, 62, 88))
        items = self.bar_items(scr)
        self.bar_rendered = items          # ★ 存下来给点击用
        for i, (label, act, r) in enumerate(items):
            if act == "none":
                # "想执行什么"（只显示，不可点）
                scr.rrect(r, 7, fill=(92, 62, 22), outline=(210, 150, 60))
                scr.text((r[0] + 10, (r[1] + r[3]) // 2), label, 15,
                         (255, 226, 170), anchor="lm", cn=True)
            elif act == "approve:all:0":
                btn(scr, r, label, fill=(120, 60, 60), size=15, cn=True,
                    radius=7)
            elif act.startswith("approve:"):
                if act.endswith(":1"):
                    btn(scr, r, label, fill=(36, 130, 78), size=17, cn=True,
                        radius=7)
                else:
                    btn(scr, r, label, fill=(140, 64, 60), size=17, cn=True,
                        radius=7)
            elif act == "mode":
                btn(scr, r, label, fill=(40, 90, 150), size=16, cn=True,
                    radius=7)
            elif act.startswith("cand:"):
                on = act == "cand:0"
                btn(scr, r, label,
                    fill=(90, 70, 30) if on else (44, 56, 84),
                    size=20, cn=True, radius=7, outline=(240, 190, 90) if on
                    else (70, 82, 110))
            else:
                btn(scr, r, label, fill=(36, 62, 52), size=16, cn=True,
                    radius=7, outline=(60, 110, 90))
        # 右侧提示
        if self.pending:
            hint = "小白想做上面的操作，等你点头"
        elif not self.py:
            hint = "打拼音选字"
        else:
            hint = "空格上屏首个 · 退格删字母"
        scr.text((CAND_RECT[2] - 8, (CAND_RECT[1] + CAND_RECT[3]) // 2),
                 hint, 14, (120, 135, 165), anchor="rm", cn=True)

        self.kb.draw(scr)


def run(scr, touch):
    app = AgentApp()
    while True:
        app.pump()
        btns = app.buttons(scr)
        app.draw(scr, btns)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            done = False
            for name, act, r in btns:
                if hit(r, x, y):
                    if act == "voice":
                        app.out("开始语音闭环：麦克风 -> 识别 -> 思考 -> 喇叭 ...")
                        app.voice(4.0)
                    elif act == "ask":
                        if app.cur.strip() and not app.busy:
                            app.out("我> " + app.cur)
                            app.ask(app.cur.strip())
                            app.cur = ""
                    elif act == "say":
                        app.say()
                    elif act == "listen":
                        app.listen(4.0)
                    elif act == "selftest":
                        app.selftest()
                    elif act == "probe":
                        app.out("正在重新检查服务 ...")
                        app._probe()
                    elif act == "clear":
                        app.lines = []
                    done = True
                    break
            if done:
                continue
            # ★ 先看候选栏（候选字 / 常用指令 / 模式切换）
            hitbar = False
            # ★ 只对**屏幕上画出来的那一份**做命中测试（所见即所点）
            for label, act, r in app.bar_rendered:
                if not hit(r, x, y):
                    continue
                hitbar = True
                if act == "none":
                    pass
                elif act.startswith("approve:"):
                    _, rid, okf = act.split(":")
                    app._approve(rid, okf == "1")
                elif act == "mode":
                    app.pinyin = not app.pinyin
                    app.py = ""
                    app.refresh_cands()
                elif act.startswith("cand:"):
                    app.commit(label)
                elif act.startswith("quick:"):
                    q = act[6:]
                    if not app.busy:
                        app.out("我> " + q)
                        app.ask(q)
                        app.cur = ""
                break
            if hitbar:
                continue

            k = app.kb.press(x, y)
            if k is not None:
                if k == "<BS>":
                    if app.py:                       # 先删拼音字母
                        app.py = app.py[:-1]
                        app.refresh_cands()
                    else:
                        app.cur = app.cur[:-1]
                elif k == "<ENTER>":
                    if app.commit_first():           # 有拼音 -> 先上屏
                        pass
                    elif app.cur.strip() and not app.busy:
                        app.out("我> " + app.cur)
                        app.ask(app.cur.strip())
                        app.cur = ""
                elif k == " ":
                    if not app.commit_first():       # 有拼音 -> 上屏首个候选
                        app.cur += " "
                else:
                    if app.pinyin and k.isalnum():
                        app.py += k.lower()          # 字母进拼音缓冲
                        app.refresh_cands()
                    else:
                        app.cur += k
        time.sleep(0.03)
