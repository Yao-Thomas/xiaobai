#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""input_panel.py —— 可复用的输入组件：语音（流式）+ 手写

════════════════════════════════════════════════════════════════════
为什么单独抽一个模块（而不是从 apps_agent.py 复制粘贴）
════════════════════════════════════════════════════════════════════
需求：把「手写 / 语音输入」也接到【浏览器】应用上。

第一反应是把 apps_agent.py 里那 700 行复制过去。但看过代码后不行：
apps_agent 的输入面板和一堆 Agent 特有的东西纠缠在一起 ——
    · self.q（后台结果队列）、self.busy、self.out()、self._bg()
    · self.msgs / self.sessions / 侧栏 / 消息区布局
    · LOG_RECT / MAIN_X0 / SIDE_RECT 这些只对 Agent 有意义的常量
直接复制会把这些依赖一起拖进浏览器，两边都变脆。

⇒ 所以抽成这个模块：**组件自己完整，只通过几个回调跟宿主打交道。**

════════════════════════════════════════════════════════════════════
宿主（App）需要提供什么
════════════════════════════════════════════════════════════════════
    get_text()      -> str      读当前输入框内容
    set_text(s)                 写回输入框
    redraw()                    请求重画（组件改完文字后调）
    notify(s)       （可选）    提示/日志
    submit(s)       （可选）    点「发送」时调用

就这四个。组件不碰宿主的其它任何东西。

════════════════════════════════════════════════════════════════════
两个组件
════════════════════════════════════════════════════════════════════
    VoicePad   按住说话：按下开始录 → 每 1.2 秒流式出字 → 松开发送
               自带 [退格] [清空] [重说] [发送]
    HandPad    手写画板：写 → 识别（百度手写 OCR）→ 上屏
               自带 [识别] [清除] [撤销] [退格] [发送]
"""

import json
import os
import time
import urllib.request

# 音频服务（板子上常驻）
AUDIO_URL = os.environ.get("XIAOBAI_AUDIO", "http://127.0.0.1:8767")

# ---- 配色（跟 apps_agent 的语音/手写面板一致，看不出是两套代码）----
C_BG = (26, 16, 12)
C_BAR = (38, 22, 18)
C_BAR_LINE = (70, 50, 40)
C_TXT = (232, 236, 242)
C_DIM = (150, 150, 155)
C_RED = (170, 55, 55)
C_RED_LINE = (200, 120, 120)
C_WARN = (255, 210, 140)
C_GREEN = (46, 96, 72)
C_GREEN_LINE = (90, 170, 130)
C_BTN = (52, 58, 70)
C_BTN_OFF = (40, 44, 52)
C_SEND_ON = (40, 110, 70)
C_PAPER = (248, 248, 246)
C_INK = (18, 18, 22)


def _hit(r, x, y):
    return bool(r) and r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _post(path, data, timeout=15):
    """POST JSON 到音频/agent 服务"""
    req = urllib.request.Request(
        path, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ══════════════════════════════════════════════════════════════════
#  语音面板
# ══════════════════════════════════════════════════════════════════
class VoicePad(object):
    """按住说话（流式识别）

    交互：
        down 在【大按钮】上  -> 开始录音 + 起流式识别线程
        move 移出按钮        -> 标记"松手取消"
        up   还在按钮上      -> 停录音 + 最后识别一次 + 上屏
        up   已在按钮外      -> 丢弃这段
        click 在小按钮上     -> 退格 / 清空 / 重说 / 发送

    ★ 流式的做法（和 apps_agent 一致，踩过坑的地方都在注释里）：
      按下就开始录，后台每 1.2 秒：
        ① 向音频服务要"当前录音快照"（/record/snapshot，不停录音）
        ② 用静音把话切成句：已说完的【定稿】缓存住，只重识别最后那句
        ③ 覆盖输入框
      松开做最后一次完整识别。
    """

    # 大按钮右边留出小键位（面板宽度 ≥ 700 时才放得下）
    HOLD_MS = 0.4          # 短于这个算误触

    def __init__(self, rect, get_text, set_text, redraw,
                 notify=None, submit=None, hint=""):
        self.rect = list(rect)          # [x0, y0, x1, y1] 面板区域
        self.get_text = get_text
        self.set_text = set_text
        self.redraw = redraw
        self.notify = notify or (lambda s: None)
        self.submit = submit or (lambda s: None)
        self.hint = hint

        self.recording = False
        self.rec_cancel = False
        self.rec_t0 = 0.0
        self.voice_text = ""
        self.voice_seq = 0
        self._prefix = ""
        self._stop = None
        self.msg = ""

        # 子区域（draw 时算好，click/down 时用）
        self.big = None
        self.btn_back = None
        self.btn_clr = None
        self.btn_re = None
        self.btn_send = None
        self._bar = None

    # ---------------- 布局 ----------------
    def _layout(self):
        x0, y0, x1, y1 = self.rect
        self._bar = [x0 + 12, y0 + 4, x1 - 12, y0 + 32]
        by0, by1 = y0 + 40, y1 - 34
        self.big = [x0 + 120, by0, x1 - 300, by1]
        ry0, ry1 = y1 - 28, y1 - 4
        self.btn_send = [x0 + 12, ry0, x0 + 132, ry1]
        self.btn_back = [x1 - 356, ry0, x1 - 268, ry1]
        self.btn_clr = [x1 - 260, ry0, x1 - 172, ry1]
        self.btn_re = [x1 - 164, ry0, x1 - 76, ry1]

    # ---------------- 绘制 ----------------
    def draw(self, scr):
        from fbui import btn
        self._layout()
        x0, y0, x1, y1 = self.rect
        scr.rect([x0, y0, x1, y1], fill=C_BG)

        # 状态条
        b = self._bar
        scr.rrect(b, 8, fill=C_BAR, outline=C_BAR_LINE)
        if self.recording:
            held = time.time() - self.rec_t0
            if self.rec_cancel:
                tip, col = "松开取消（手指已移出按钮）", C_WARN
            else:
                tip, col = ("● 正在聆听 %.1fs  松开发送" % held), (255, 140, 140)
        elif self.msg:
            tip, col = self.msg, C_WARN
        else:
            tip = self.hint or "按住下面的大按钮说话；手指上滑出按钮再松手 = 取消"
            col = (200, 200, 205)
        scr.text((b[0] + 12, (b[1] + b[3]) // 2), tip, 16, col,
                 anchor="lm", cn=True)

        # 大按钮
        br = self.big
        if self.recording:
            fill = (90, 90, 90) if self.rec_cancel else C_RED
            label = "松开取消" if self.rec_cancel else "● 聆听中…"
            outline = C_RED_LINE
        else:
            fill, label, outline = C_GREEN, "按住 说 话", C_GREEN_LINE
        scr.rrect(br, 24, fill=fill, outline=outline,
                  width=3 if self.recording else 2)
        scr.text(((br[0] + br[2]) // 2, (br[1] + br[3]) // 2 - 8), label, 30,
                 (255, 255, 255), anchor="mm", cn=True)

        # 小键
        has = bool((self.get_text() or "").strip())
        btn(scr, self.btn_send, "发 送",
            fill=C_SEND_ON if has else C_BTN_OFF, size=15, cn=True, radius=8)
        scr.text((self.btn_send[2] + 12, (self.btn_send[1] +
                 self.btn_send[3]) // 2), "回车是换行，发出去要点这里", 13,
                 C_DIM, anchor="lm", cn=True)
        for r, label, on in ((self.btn_back, "退格", has),
                             (self.btn_clr, "清空", has),
                             (self.btn_re, "重说",
                              bool(self.voice_text))):
            btn(scr, r, label, fill=C_BTN if on else C_BTN_OFF,
                size=14, cn=True, radius=8)

    # ---------------- 点击（小键）----------------
    def click(self, x, y):
        if _hit(self.btn_send, x, y):
            t = (self.get_text() or "").strip()
            if t:
                self.submit(t)
            return True
        if _hit(self.btn_back, x, y):
            cur = self.get_text() or ""
            if cur:
                self.set_text(cur[:-1])
                self.redraw()
            return True
        if _hit(self.btn_clr, x, y):
            self.set_text("")
            self.voice_text = ""
            self.redraw()
            return True
        if _hit(self.btn_re, x, y):
            # ★ 只清掉本次听出来的，保留录音前已有的字
            self.set_text(self._prefix or "")
            self.voice_text = ""
            self.msg = "已清空，可以重新按住说话"
            self.redraw()
            return True
        return False

    def down(self, x, y):
        if _hit(self.big, x, y):
            self.begin()
            return True
        return False

    def move(self, x, y):
        if self.recording:
            self.rec_cancel = not _hit(self.big, x, y)
            self.redraw()
            return True
        return False

    def up(self, x, y):
        if self.recording:
            self.end(cancel=self.rec_cancel)
            return True
        return False

    # ---------------- 录音 + 流式 ----------------
    def begin(self):
        self.recording = True
        self.rec_cancel = False
        self.rec_t0 = time.time()
        self.voice_text = ""
        self.voice_seq = 0
        self.msg = ""
        self._prefix = self.get_text() or ""

        def _start():
            try:
                _post(AUDIO_URL + "/record/start", {}, timeout=15)
            except Exception as e:
                self.msg = "录音启动失败: %s" % e
        import threading as _th
        _th.Thread(target=_start, daemon=True).start()

        self._stop = _th.Event()
        _th.Thread(target=self._loop, daemon=True).start()
        self.notify("● 正在聆听…（边说边出字；松开发送 · 上滑取消）")

    def _loop(self):
        """后台流式识别循环（每 1.2 秒一轮）"""
        import sys as _s
        if "/home/zynq" not in _s.path:
            _s.path.insert(0, "/home/zynq")
        try:
            from agent import asr as _asr
        except Exception:
            return
        committed, csec, last = "", 0.0, ""
        SNAP, CUR, NEW = ("/tmp/_pad_snap.wav", "/tmp/_pad_cur.wav",
                          "/tmp/_pad_new.wav")
        while not self._stop.is_set():
            if self._stop.wait(1.2):
                break
            if not self.recording:
                break
            try:
                wav = _post(AUDIO_URL + "/record/snapshot",
                            {"rate": 16000}, timeout=12)
                if wav[:4] != b"RIFF":
                    continue
                with open(SNAP, "wb") as f:
                    f.write(wav)

                b = 0.0
                try:
                    b = _asr.last_boundary(SNAP)
                except Exception:
                    b = 0.0

                # 超长保护：当前句 > 18 秒就强制定稿一半
                try:
                    import wave as _wv
                    with _wv.open(SNAP, "rb") as _wf:
                        _r = _wf.getframerate() or 16000
                        total = _wf.getnframes() / float(_r)
                except Exception:
                    total = 0.0
                if total > 18.0 and (total - csec) > 18.0:
                    cut = max(csec + 1.0, total - 6.0)
                    if _asr.slice_wav(SNAP, CUR, csec, cut, ctx=0.35):
                        if _asr.has_speech(CUR):
                            t0, _ = _asr.recognize(CUR, rate=16000)
                            if t0:
                                committed = (committed + t0).strip()
                        csec = cut
                        b = cut

                # 定稿段
                if b > csec + 0.15:
                    if _asr.slice_wav(SNAP, CUR, csec, b, ctx=0.35):
                        if _asr.has_speech(CUR):
                            t1, _ = _asr.recognize(CUR, rate=16000)
                            if t1:
                                committed = (committed + t1).strip()
                        csec = b

                # 当前句
                txt = ""
                if _asr.slice_wav(SNAP, NEW, csec, None, ctx=0.35):
                    if _asr.has_speech(NEW):
                        t2, _ = _asr.recognize(NEW, rate=16000)
                        txt = (t2 or "").strip()
                else:
                    t2, _ = _asr.recognize(SNAP, rate=16000)
                    txt = (t2 or "").strip()
                    committed, csec = "", 0.0

                full = (committed + txt).strip()
                if full and full != last:
                    last = full
                    self.voice_text = full
                    self.set_text((self._prefix or "") + full)
                    self.redraw()
            except Exception:
                continue

    def end(self, cancel=False):
        self.recording = False
        cancel = bool(cancel or self.rec_cancel)
        self.rec_cancel = False
        held = max(0.0, time.time() - self.rec_t0)
        try:
            if self._stop:
                self._stop.set()
        except Exception:
            pass
        if held < self.HOLD_MS and not cancel:
            cancel = True

        def _fin():
            try:
                raw = _post(AUDIO_URL + "/record/stop",
                            {"cancel": cancel, "rate": 16000}, timeout=30)
            except Exception as e:
                self.msg = "停止录音失败: %s" % e
                self.redraw()
                return
            if cancel:
                self.msg = "已取消（按住 %.1fs）" % held
                self.redraw()
                return
            if raw[:4] != b"RIFF":
                self.msg = "录音没拿到音频"
                self.redraw()
                return
            wav = "/tmp/_pad_hold.wav"
            try:
                with open(wav, "wb") as f:
                    f.write(raw)
                import sys as _s
                if "/home/zynq" not in _s.path:
                    _s.path.insert(0, "/home/zynq")
                from agent import asr
                text, eng = asr.recognize(wav, rate=16000)
            except Exception as e:
                text, eng = "", "err:%s" % e
            streamed = (self.voice_text or "").strip()
            if not text:
                text = streamed          # 别让用户白说
            if not text:
                self.msg = "没听清，再说一次？"
                self.redraw()
                return
            # ★ 有流式结果且是完整段的前缀时，用完整段的（更准）
            self.set_text((self._prefix or "") + text)
            self.voice_text = text
            self.msg = "听到：%s" % text[:40]
            self.redraw()
        import threading as _th
        _th.Thread(target=_fin, daemon=True).start()
        self.notify("● 正在识别…")


# ══════════════════════════════════════════════════════════════════
#  手写面板
# ══════════════════════════════════════════════════════════════════
class HandPad(object):
    """手写画板：写 -> 识别（百度手写 OCR）-> 上屏

    ★★★ 性能设计（这一版是重写过的，之前"特别卡"）
    ────────────────────────────────────────────────────────────────
    老实现每收到一个 move 事件就：整块重画面板 + 整屏 flush。
    板子上实测：
        整屏 flush()                37 ms   （推 1.8MB）
        flush(box=整个面板)         70 ms   ★ 局部反而更慢
        画板本身（paste+画线）      16 ms
    ⇒ 一次划动 30 个 move 要 1.8 秒 = 17 帧/秒，手感就是"特别卡"。

    现在分三层：
        ① 静态层 _static —— 白底 + 【所有已抬笔的笔迹】。只在落笔结束时重建。
        ② 工作层 _panel  —— 静态层 + 正在写的这一笔。增量追加，不重画。
        ③ 每帧只推【脏矩形】—— 就是这一小段的包围盒，用 blit_raw 直写显存，
           不走 crop+convert+逐行循环那条慢路（实测 1~3ms）。
    ⇒ 划动时每帧只跟"这一小段"的像素打交道，跟画板上有多少字无关。
    ────────────────────────────────────────────────────────────────
    """

    def __init__(self, rect, get_text, set_text, redraw,
                 notify=None, submit=None):
        self.rect = list(rect)
        self.get_text = get_text
        self.set_text = set_text
        self.redraw = redraw
        self.notify = notify or (lambda s: None)
        self.submit = submit or (lambda s: None)

        self.strokes = []        # 已抬笔的笔迹 [[(x,y),...], ...]
        self.cur = None          # 正在写的这一笔
        self.msg = ""
        self.busy = False

        self._bg = None          # 白底（面板尺寸）
        self._static = None      # 白底 + 已抬笔笔迹
        self._panel = None       # 工作层（静态层 + 当前笔）
        self._dirty = None       # 本帧要推的矩形（面板坐标）
        self._committed = None   # 兼容旧名字（= _static）
        self.buttons = []

    def _layout(self):
        x0, y0, x1, y1 = self.rect
        by0, by1 = y1 + 8, y1 + 42
        b = []
        x = x0
        for label, act, w in (("识 别", "recog", 100),
                              ("清 除", "clear", 100),
                              ("撤 销", "undo", 100),
                              ("退 格", "bs", 100)):
            b.append((label, act, [x, by0, x + w, by1]))
            x += w + 8
        b.append(("发 送", "send", [x1 - 250, by0, x1 - 140, by1]))
        self.buttons = b

    def draw(self, scr):
        """整块重画面板（进入手写模式 / 清除 / 撤销 / 识别完成后用）

        ★ 这条路会 flush 整屏（约 37ms），所以【只在必要时走】。
          手指划动的每一帧走 blit() —— 那只推脏矩形，1~3ms。
        """
        from fbui import btn
        self._layout()
        self._ensure_buffers()
        x0, y0, x1, y1 = self.rect

        # ★★★ 只刷【画板下方按钮条】—— 2026-10-03 修显示 bug
        # ────────────────────────────────────────────────────────────────
        # 用户报："点语音的时候输入框是正常的，但是点手写不是，主要是显示问题"
        #
        # 根因：这里原来刷的是 scr.rect([0, y0-45, 1024, y0])，也就是
        #   265..310 那一条。而浏览器输入框在 [16, 272, 1008, 306] ——
        #   正好整条落在这个范围里 ⇒ 切到手写，输入框被刷没了。
        #
        #   对比 VoicePad：它只刷 scr.rect([x0, y0, x1, y1])（310 往下），
        #   压根不碰输入框 —— 所以语音模式看起来正常。
        #
        # ⇒ 画板不该往自己【上方】刷。上方（模式按钮 246..276、提示 258、
        #   输入框 272..306）都是宿主画好的，刷了就是把人家的东西擦掉。
        # ────────────────────────────────────────────────────────────────
        scr.rect([0, y1, 1024, 600], fill=C_BG)

        # 面板本体：一次 paste（_static 里已经含所有已抬笔的笔迹）
        scr.img.paste(self._static, (x0, y0))
        # 正在写的那一笔
        if self.cur and len(self.cur) >= 2:
            pts = [(px - x0, py - y0) for px, py in self.cur]
            scr.d.line([(px + x0, py + y0) for px, py in pts],
                       fill=C_INK, width=6, joint="curve")
        elif self.cur:
            px, py = self.cur[0]
            scr.d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=C_INK)

        if self.msg:
            scr.text((512, y1 + 26), self.msg, 14, C_WARN, anchor="mm",
                     cn=True)
        for label, act, r in self.buttons:
            fill = C_BTN
            if act == "send":
                fill = (C_SEND_ON if (self.get_text() or "").strip()
                        else C_BTN_OFF)
            btn(scr, r, label, fill=fill, size=15, cn=True, radius=8)
        scr.flush()

    # ---------------- ★★★ 快路径：只推脏矩形 ----------------
    def blit(self, scr):
        """把【这一帧真正变了的那个小矩形】推到显存

        为什么快（实测对比，板子上量的）：
            整屏 flush()            37 ms   （推 1.8MB）
            flush(box=整个面板)     70 ms   ★ 反而更慢：内部是
                                            crop+convert+【逐行 Python 循环】
            本方法（blit_raw）      ~1-3 ms 只有一次 crop + 小 convert + memcpy
        手指划一笔会触发几十次 move，每次都 37ms ⇒ 17 帧/秒，这就是"特别卡"。
        """
        d = self._dirty
        self._dirty = None
        if not d:
            return
        x0, y0, x1, y1 = d
        if x1 <= x0 or y1 <= y0:
            return
        try:
            sub = self._panel.crop((x0, y0, x1, y1))
            scr.blit_raw(self.rect[0] + x0, self.rect[1] + y0,
                         x1 - x0, y1 - y0, scr.to_raw(sub))
        except Exception:
            # 快路径出任何问题就退回整块重画，宁可慢也别画错
            self._dirty = (0, 0, self.rect[2] - self.rect[0],
                           self.rect[3] - self.rect[1])
            self.draw(scr)

    def _ensure_buffers(self):
        """准备三张面板尺寸的图：静态层 / 工作层 / 底色"""
        from PIL import Image as _I
        w = max(1, self.rect[2] - self.rect[0])
        h = max(1, self.rect[3] - self.rect[1])
        if getattr(self, "_panel", None) is None or self._panel.size != (w, h):
            self._panel = _I.new("RGB", (w, h), C_PAPER)
            self._static = None
            self._dirty = None
        if getattr(self, "_static", None) is None:
            self._rebuild_static()

    def _rebuild_static(self):
        """静态层 = 白底 + 所有已抬笔的笔迹（面板坐标系）

        ★ 分成"静态层 + 当前笔"两层是关键：
          已抬笔的笔迹不会再变 ⇒ 烧成一张图，每帧只 paste 一次；
          正在写的只画一小段 ⇒ 每帧只推那一小段。
        """
        from PIL import Image, ImageDraw
        self._static = self._bg_img().copy()
        d = ImageDraw.Draw(self._static)
        x0, y0 = self.rect[0], self.rect[1]
        for st in self.strokes:
            pts = [(px - x0, py - y0) for px, py in st]
            if len(pts) >= 2:
                d.line(pts, fill=C_INK, width=6, joint="curve")
            elif pts:
                d.ellipse([pts[0][0] - 3, pts[0][1] - 3,
                           pts[0][0] + 3, pts[0][1] + 3], fill=C_INK)
        if getattr(self, "_panel", None) is not None:
            self._panel.paste(self._static)

    def _bg_img(self):
        if self._bg is None:
            from PIL import Image as _I
            from PIL import ImageDraw as _ID
            w = max(1, self.rect[2] - self.rect[0])
            h = max(1, self.rect[3] - self.rect[1])
            im = _I.new("RGB", (w, h), C_PAPER)
            d = _ID.Draw(im)
            d.line([24, h // 2, w - 24, h // 2], fill=(226, 226, 222), width=1)
            self._bg = im
        return self._bg

    def _commit_strokes(self):
        """兼容旧名字（外部测试用过）"""
        self._rebuild_static()

    # ---------------- 触摸 ----------------
    def down(self, x, y):
        if not _hit(self.rect, x, y):
            return False
        self._ensure_buffers()
        self.cur = [(x, y)]
        # 落笔先画个点，免得第一下没反应
        from PIL import ImageDraw
        px, py = x - self.rect[0], y - self.rect[1]
        d = ImageDraw.Draw(self._panel)
        d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=C_INK)
        self._dirty = self._clip(px - 5, py - 5, px + 6, py + 6)
        return True

    def move(self, x, y):
        if self.cur is None:
            return False
        x0, y0, x1, y1 = self.rect
        px = max(x0, min(x1, x))
        py = max(y0, min(y1, y))
        prev = self.cur[-1]
        if (px, py) == prev:
            return True
        self.cur.append((px, py))
        a = (prev[0] - x0, prev[1] - y0)
        b = (px - x0, py - y0)
        from PIL import ImageDraw
        # ★ 只【追加】画这一小段，不重画整笔：
        #   面板工作层上已经保留了前面画过的笔画，不需要每帧重来。
        #   （重复画同一段也无害，同色不透明）
        ImageDraw.Draw(self._panel).line([a, b], fill=C_INK, width=6)
        m = 4
        self._dirty = self._clip(min(a[0], b[0]) - m, min(a[1], b[1]) - m,
                                 max(a[0], b[0]) + m + 1,
                                 max(a[1], b[1]) + m + 1)
        return True

    def _clip(self, x0, y0, x1, y1):
        w = self.rect[2] - self.rect[0]
        h = self.rect[3] - self.rect[1]
        return (max(0, int(x0)), max(0, int(y0)),
                min(w, int(x1)), min(h, int(y1)))

    def up(self, x, y):
        if self.cur is None:
            return False
        if len(self.cur) >= 1:
            self.strokes.append(self.cur)
        self.cur = None
        # ★ 这一笔已经通过增量 blit 上屏了，所以 up 不需要再推一帧；
        #   只要把静态层重建（含这一笔），供下次重画用。
        self._rebuild_static()
        return True

    def click(self, x, y, scr=None):
        """处理面板上的按钮

        ★ scr 传进来时，动作做完就地重画【面板这一块】并 flush 一次。
          不传就退回宿主回调（那会触发整页重排，慢得多）。
          为什么加这个参数：清除/撤销/退格只影响画板和自己那块按钮，
          没必要让浏览器把整个 HTML 页面重排一遍（实测 157ms/次）。
        """
        for label, act, r in self.buttons:
            if not _hit(r, x, y):
                continue
            if act == "send":
                t = (self.get_text() or "").strip()
                if t:
                    self.submit(t)
            elif act == "recog":
                self.recognize(scr)
            elif act == "clear":
                self.strokes = []
                self.cur = None
                self.msg = ""
                self._reset_panel(scr)
            elif act == "undo":
                if self.strokes:
                    self.strokes.pop()
                self._reset_panel(scr)
            elif act == "bs":
                cur = self.get_text() or ""
                if cur:
                    self.set_text(cur[:-1])
                    self._reset_panel(scr)
            return True
        return False

    def _reset_panel(self, scr):
        """笔迹变了（清除/撤销）之后：重建静态层并重画面板"""
        self._dirty = None
        self._ensure_buffers()
        self._rebuild_static()
        if scr is not None:
            # 面板 + 下方按钮（发送键的可用态可能变了）一起重画
            self._layout()
            self.draw(scr)
        else:
            self.redraw()

    # ---------------- 识别 ----------------
    def strokes_to_png(self):
        """把笔迹渲染成白底黑字 PNG（按笔迹范围裁剪 + 缩放到百度要的尺寸）

        ★★★ 为什么要裁剪 + 缩放（照抄 apps_agent 的实测结论）：
          · 直接把整个画板（1000x450）发过去，字只占中间一小块，
            百度在小字上识别率明显下降
          · 百度手写 OCR 的硬要求：**最短边 >= 15px**
            （太小直接报错），最长边别超 4096
          ⇒ 按笔迹的实际包围盒裁出来，再缩放到合适大小。
        ★ 返回 PNG 字节；没有笔迹返回 None。
        """
        import io as _io
        from PIL import Image, ImageDraw

        xs = [p[0] for st in self.strokes for p in st]
        ys = [p[1] for st in self.strokes for p in st]
        if not xs:
            return None
        pad = 26
        bx0, bx1 = min(xs) - pad, max(xs) + pad
        by0, by1 = min(ys) - pad, max(ys) + pad
        w, h = max(8, bx1 - bx0), max(8, by1 - by0)
        scale = 1.0
        if min(w, h) < 15:
            scale = 15.0 / min(w, h)
        if max(w, h) * scale > 1400:
            scale = 1400.0 / max(w, h)
        W2, H2 = max(15, int(w * scale)), max(15, int(h * scale))
        im = Image.new("RGB", (W2, H2), (255, 255, 255))
        d = ImageDraw.Draw(im)
        lw = max(6, int(6 * scale))
        for st in self.strokes:
            pts = [((px - bx0) * scale, (py - by0) * scale) for px, py in st]
            if len(pts) >= 2:
                d.line(pts, fill=(0, 0, 0), width=lw, joint="curve")
            elif pts:
                d.ellipse([pts[0][0] - 2, pts[0][1] - 2,
                           pts[0][0] + 2, pts[0][1] + 2], fill=(0, 0, 0))
        buf = _io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    def recognize(self, scr=None):
        """把笔迹渲染成 PNG -> 百度手写 OCR -> 上屏

        ★ scr 给进来时，"识别中…" 这个提示就地画（省一次整页重排）；
          识别完成后输入框里的字变了 —— 那个必须让宿主重画（它管输入框），
          所以那一步照旧调 self.redraw()。
        """
        if not self.strokes:
            self.msg = "先写几个字"
            self._reset_panel(scr)
            return
        if self.busy:
            return
        self.busy = True
        self.msg = "识别中…"
        self._reset_panel(scr)

        def _work():
            try:
                png = self.strokes_to_png()
                if not png:
                    self.msg = "画板是空的"
                    return
                text, err = handwriting_ocr(png)
                if text:
                    self.set_text((self.get_text() or "") + text)
                    self.strokes = []
                    self._rebuild_static()
                    self.msg = "识别: %s" % text
                else:
                    self.msg = (err or "没认出来，再写清楚点？")[:70]
            except Exception as e:
                self.msg = "识别失败: %s" % str(e)[:50]
            finally:
                self.busy = False
                # ★ 输入框里的字变了，必须让宿主整体重画一次（一次而已）
                self.redraw()

        import threading as _th
        _th.Thread(target=_work, daemon=True).start()


# ══════════════════════════════════════════════════════════════════
#  百度手写 OCR
# ══════════════════════════════════════════════════════════════════
def handwriting_ocr(png_bytes):
    """把手写图片送百度手写 OCR，返回 (文字, 错误说明)

    ★★★ 两套 key 的坑（照抄 apps_agent 的现场记录）
    ────────────────────────────────────────────────────────────────
    百度智能云的【语音技术】和【文字识别】是**两个独立的应用**，
    各有一对 API Key / Secret Key。在语音应用上勾「文字识别」是勾不上的，
    所有 OCR 接口会返回 error_code 6 (No permission)。

    ⇒ 所以优先读 OCR 专用凭据文件 /etc/zynq-baidu-ocr.env；
       没有就退回语音那套（万一哪天账号开通了）。
    ⇒ error 6 时给一句人话，而不是把错误码甩给用户。
    ────────────────────────────────────────────────────────────────
    """
    try:
        import base64 as _b64
        import urllib.parse as _up
        import urllib.request as _u
        import sys as _sys
        if "/home/zynq" not in _sys.path:
            _sys.path.insert(0, "/home/zynq")
        from agent import tts
    except Exception as e:
        return "", "环境不对: %s" % e

    # ---- ① 拿 token（优先 OCR 专用 key）----
    ocr_k = ocr_s = ""
    try:
        with open("/etc/zynq-baidu-ocr.env", encoding="utf-8",
                  errors="replace") as f:
            for ln in f:
                if ln.startswith("BAIDU_API_KEY="):
                    ocr_k = ln.split("=", 1)[1].strip()
                elif ln.startswith("BAIDU_SECRET_KEY="):
                    ocr_s = ln.split("=", 1)[1].strip()
    except Exception:
        pass

    try:
        if ocr_k and ocr_s:
            q = _up.urlencode({"grant_type": "client_credentials",
                               "client_id": ocr_k, "client_secret": ocr_s})
            with tts._urlopen(
                    "https://aip.baidubce.com/oauth/2.0/token?" + q, 20) as r:
                td = json.loads(r.read().decode("utf-8", "replace"))
            tok = td.get("access_token") or ""
            if not tok:
                return "", "OCR 应用拿不到 token"
        else:
            tok = tts.token()
    except Exception as e:
        return "", "拿 token 失败: %s" % str(e)[:50]

    # ---- ② 调手写识别 ----
    try:
        url = ("https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"
               "?access_token=" + tok)
        body = _up.urlencode(
            {"image": _b64.b64encode(png_bytes).decode()}).encode()
        req = _u.Request(url, data=body,
                         headers={"Content-Type":
                                  "application/x-www-form-urlencoded"},
                         method="POST")
        # ★ 用 tts._urlopen —— 它带 CA 兜底（板子系统 CA 不全）
        with tts._urlopen(req, 30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return "", "请求失败: %s" % str(e)[:50]

    if d.get("error_code"):
        ec = str(d.get("error_code"))
        if ec == "6":
            return "", ("手写识别没开通：百度智能云的「文字识别」要和"
                        "「语音技术」分开建应用，把那对 key 放到 "
                        "/etc/zynq-baidu-ocr.env")
        return "", "手写识别失败: %s %s" % (ec, d.get("error_msg"))
    words = d.get("words_result") or []
    text = "".join(str(x.get("words", "")) for x in words)
    if not text:
        return "", "没认出来（写大一点、字分开一点再试）"
    return text, ""
