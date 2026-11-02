#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_inputmode.py —— 统一输入面板：键盘 / 语音 / 手写 三合一

════════════════════════════════════════════════════════════════════
用户："语音和手写是不是可以一起，毕竟同一套"
      "1. 统一输入面板 = 键盘 + 语音 + 手写 ← 抽象定对了再加第三套"

设计
════════════════════════════════════════════════════════════════════
三种输入方式【共用的】：
  · 同一个输入框 self.cur
  · 同一套提交路径（回车发送 / await_text 提交 Key 或模型名）
  · 同一个"面板展开"状态（原来叫 kb_open）
  · 同一套取消语义
  · 同一个 Touch 的 down/move/up

【不同的】只有"怎么把用户的动作变成文字"：
  ┌────────┬──────────────────┬────────────────────┬──────────────┐
  │ 键盘   │ 按键             │ 直接是字符          │ 点            │
  │ 语音   │ 长按期间的时间流  │ 音频 → 百度 ASR     │ 按住/松开/上滑 │
  │ 手写   │ 画板上的空间轨迹  │ 轨迹→PNG→百度手写OCR│ 落笔/移动/抬笔 │
  └────────┴──────────────────┴────────────────────┴──────────────┘

实现方式（低风险）
════════════════════════════════════════════════════════════════════
不重写整个 App，只把两件事抽成"按 in_mode 分发"：
  ① draw_input_panel(scr)   —— 原来 draw() 里 `if self.kb_open:` 那一大段
  ② input_panel_click(x,y)  —— 原来 run() 里直接调 self.kb_click(x,y)

★ 键盘那条路【一行没改】，只是被搬进了 draw_keyboard_panel()。
  这样抽象错了也不会把已经好用的键盘搞坏。
════════════════════════════════════════════════════════════════════
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
P = os.path.join(HERE, "apps_agent.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    lines = src.split("\n")
    orig = src
    print("=" * 70)
    print(" 统一输入面板：键盘 / 语音 / 手写")
    print("=" * 70)

    # ── ① 常量 ──
    anchor_const = "def rect_in(scr, kb_open):"
    const_block = '''# ══════════════════════════════════════════════════════════════════
#  ★★★ 输入方式（统一输入面板，2026-10-03）
# ══════════════════════════════════════════════════════════════════
# 用户："语音和手写是不是可以一起，毕竟同一套"
#  三种输入方式共用：输入框 self.cur / 提交路径 / 取消语义 / down-up 事件
#  只有"怎么把动作变成文字"不同，所以按 in_mode 分发就行。
IN_KB = "kb"          # 键盘：候选栏 + 软键盘
IN_VOICE = "voice"    # 语音：按住说话 -> 百度 ASR
IN_HAND = "hand"      # 手写：画板 -> 百度手写 OCR
IN_MODES = (IN_KB, IN_VOICE, IN_HAND)
IN_MODE_LABEL = {IN_KB: "键盘", IN_VOICE: "语音", IN_HAND: "手写"}


'''
    if anchor_const in src and "IN_HAND = " not in src:
        src = src.replace(anchor_const, const_block + anchor_const, 1)
        print("   ✓ 加了 IN_KB / IN_VOICE / IN_HAND 常量")
    else:
        print("   ✗ 常量锚点没找到")

    # ── ② __init__ 状态 ──
    anchor_init = "        self.kb_open = False            # 键盘默认收起（点输入框才弹）"
    init_block = '''        self.kb_open = False            # ★ 面板展开（旧名保留：三种输入共用）
        # ══════════════════════════════════════════════════════════
        #  ★★★ 统一输入面板状态（2026-10-03）
        #     in_mode 决定面板展开时【显示哪一套】：
        #       "kb" 键盘 / "voice" 语音 / "hand" 手写
        #     三者共用 self.cur 和提交路径，只有采集方式不同。
        # ══════════════════════════════════════════════════════════
        self.in_mode = IN_KB
        self.hand_strokes = []       # 手写：[[(x,y),...], ...] 每一笔
        self.hand_cur = None         # 当前正在画的那一笔
        self.hand_msg = ""           # 手写区提示'''
    if anchor_init in src:
        src = src.replace(anchor_init, init_block, 1)
        print("   ✓ __init__ 加了 in_mode / hand_strokes 状态")
    else:
        print("   ✗ __init__ 锚点没找到")

    # ── ③ draw() 里：键盘那段 -> 分发调用 ──
    anchor_open = '''        # ★★★ 键盘 + 候选栏【只在需要时显示】
        #   600px 高的屏，常驻一个 160px 的软键盘，消息区就只剩 270px 了。
        #   所以默认收起，点输入框才弹（弹出时盖住下半屏）。
        if self.kb_open:'''
    new_open = '''        # ★★★ 输入面板【只在展开时显示】，按 in_mode 决定画哪一套
        #   600px 高的屏，常驻一个 160px 的软键盘，消息区就只剩 270px 了。
        #   所以默认收起，点输入框才弹（弹出时盖住下半屏）。
        #
        #   ★ 2026-10-03 统一输入面板：原来是写死的键盘，现在按
        #     self.in_mode 分发到 draw_keyboard_panel / draw_voice_panel /
        #     draw_hand_panel。键盘那段代码一行没改，只是搬了家。
        if self.kb_open:
            self.draw_input_panel(scr)
        else:
            self.bar_rendered = []

        # ★★★ 设置页盖在最上层
        if self.settings_open:
            self.draw_settings(scr)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 统一输入面板（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    def set_input_mode(self, m):
        """切换输入方式（按钮排上的三个小按钮）"""
        if m not in IN_MODES:
            return
        self.in_mode = m
        if m in (IN_VOICE, IN_HAND):
            self.kb_open = True        # 语音/手写也要占下半屏
            self.pinyin = False        # 别让拼音缓冲捣乱
            self.py = ""
        if m == IN_HAND:
            self.hand_msg = "在白色区域写字，写完点「识别」"
        else:
            self.hand_msg = ""

    def draw_input_panel(self, scr):
        """按当前输入方式画下半屏面板（三者共用同一块区域）"""
        m = getattr(self, "in_mode", IN_KB)
        if m == IN_HAND:
            self.draw_hand_panel(scr)
        elif m == IN_VOICE:
            self.draw_voice_panel(scr)
        else:
            self.draw_keyboard_panel(scr)

    def input_panel_click(self, x, y):
        """把点击分发给当前输入方式；True = 这次点击被面板消费掉了"""
        m = getattr(self, "in_mode", IN_KB)
        if m == IN_HAND:
            return self.hand_click(x, y)
        if m == IN_VOICE:
            return False        # 语音靠 down/up（按住说话），不走"点击"
        return self.kb_click(x, y)

    def draw_keyboard_panel(self, scr):
        """★ 键盘面板 —— 从 draw() 原样搬过来（逻辑一行没动）"""
        if self.kb_open:'''
    if anchor_open in src:
        src = src.replace(anchor_open, new_open, 1)
        print("   ✓ draw() 改成调用 draw_input_panel()")
    else:
        print("   ✗ draw() 键盘锚点没找到")

    # ── ④ 键盘面板收尾 -> 关掉 draw_keyboard_panel，再挂语音/手写方法 ──
    anchor_tail = '''            self.kb.draw(scr)
        else:
            self.bar_rendered = []

        # ★★★ 设置页盖在最上层
        if self.settings_open:
            self.draw_settings(scr)
'''
    tail_block = '''            self.kb.draw(scr)

    # ──────────────────────────────────────────────────────────────
    #  语音面板
    # ──────────────────────────────────────────────────────────────
    def voice_panel_rect(self):
        """语音面板占的区域（和键盘一样：下半屏）"""
        return [0, KB_Y - 44, 1024, 600]

    def draw_voice_panel(self, scr):
        """语音面板：大号按住说话 + 状态提示

        ★ 真正的按下/松开逻辑在 run() 里（靠 Touch 的 down/up 事件），
          这里只负责画。
        """
        scr.rect([0, KB_Y - 44, 1024, 600], fill=(26, 16, 12))
        rec = getattr(self, "recording", False)
        cancel = getattr(self, "rec_cancel", False)

        # 状态条（复用候选栏那条位置）
        cr = [190, KB_Y - 40, 1002, KB_Y - 4]
        scr.rrect(cr, 8, fill=(38, 22, 18), outline=(70, 50, 40))
        if rec:
            held = time.time() - getattr(self, "rec_t0", time.time())
            if cancel:
                tip, col = "松开取消（手指已移出按钮）", (255, 210, 140)
            else:
                tip, col = ("● 正在聆听 %.1fs  松开发送" % held,
                            (255, 140, 140))
        else:
            tip, col = ("按住下面的大按钮说话；手指上滑到按钮外松手 = 取消",
                        (200, 200, 205))
        scr.text((cr[0] + 12, (cr[1] + cr[3]) // 2), tip, 16, col,
                 anchor="lm", cn=True)

        # 大号"按住说话"
        self.voice_big = [312, KB_Y + 6, 712, 588]
        br = self.voice_big
        if rec:
            fill = (90, 90, 90) if cancel else (170, 55, 55)
            label = "松开取消" if cancel else "● 聆听中…"
            outline = (200, 120, 120)
        else:
            fill, label, outline = (46, 96, 72), "按住 说 话", (90, 170, 130)
        scr.rrect(br, 24, fill=fill, outline=outline, width=3 if rec else 2)
        scr.text(((br[0] + br[2]) // 2, (br[1] + br[3]) // 2 - 8), label, 34,
                 (255, 255, 255), anchor="mm", cn=True)
        scr.text(((br[0] + br[2]) // 2, br[3] + 10),
                 "（也可点上面的输入框，切回键盘打字）", 14, (150, 150, 155),
                 anchor="mm", cn=True)

    # ──────────────────────────────────────────────────────────────
    #  手写面板
    # ──────────────────────────────────────────────────────────────
    def hand_panel_rect(self):
        """手写画板区域"""
        return [190, KB_Y - 40, 1002, 556]

    def hand_buttons(self):
        """手写面板上的按钮"""
        x0, y0, x1, y1 = self.hand_panel_rect()
        by0, by1 = y1 + 8, 594
        b = []
        x = x0
        for label, act, w in (("识 别", "hand:recog", 100),
                              ("清 除", "hand:clear", 100),
                              ("撤 销", "hand:undo", 100),
                              ("退 格", "hand:bs", 100)):
            b.append((label, act, [x, by0, x + w, by1]))
            x += w + 8
        b.append(("切回键盘", "hand:kb", [x1 - 130, by0, x1, by1]))
        return b

    def draw_hand_panel(self, scr):
        """手写面板：白底画板 + 笔迹 + 操作按钮

        ★ 识别原理：把笔迹渲染成 PNG（白底黑字），
          发给百度手写 OCR —— 和语音共用同一个 key，不用另配。
        """
        scr.rect([0, KB_Y - 44, 1024, 600], fill=(26, 16, 12))
        r = self.hand_panel_rect()
        x0, y0, x1, y1 = r
        # 白底：百度手写 OCR 对"白底黑字"识别最好
        scr.rrect(r, 10, fill=(248, 248, 246), outline=(120, 120, 125))
        scr.d.line([x0 + 24, (y0 + y1) // 2, x1 - 24, (y0 + y1) // 2],
                   fill=(226, 226, 222), width=1)

        # 已完成的笔迹
        for st in getattr(self, "hand_strokes", []):
            if len(st) >= 2:
                scr.d.line(st, fill=(18, 18, 22), width=4, joint="curve")
            elif len(st) == 1:
                px, py = st[0]
                scr.d.ellipse([px - 2, py - 2, px + 2, py + 2],
                              fill=(18, 18, 22))
        # 正在画的那一笔
        hc = getattr(self, "hand_cur", None)
        if hc and len(hc) >= 2:
            scr.d.line(hc, fill=(18, 18, 22), width=4, joint="curve")

        if not getattr(self, "hand_strokes", []) and not hc:
            scr.text(((x0 + x1) // 2, (y0 + y1) // 2 - 36),
                     "在白色区域里写字", 24, (188, 188, 188),
                     anchor="mm", cn=True)
            scr.text(((x0 + x1) // 2, (y0 + y1) // 2 + 2),
                     "写完点下面「识 别」", 17, (198, 198, 198),
                     anchor="mm", cn=True)

        if getattr(self, "hand_msg", ""):
            scr.text((x0 + 4, y0 - 16), self.hand_msg, 15, (250, 200, 120),
                     anchor="lm", cn=True)

        for label, act, br in self.hand_buttons():
            if act == "hand:recog":
                fill = (40, 96, 70)
            elif act == "hand:kb":
                fill = (58, 50, 46)
            else:
                fill = (52, 62, 88)
            btn(scr, br, label, fill=fill, size=16, cn=True, radius=8)

    def hand_click(self, x, y):
        """手写面板的按钮点击；True = 消费掉了"""
        for label, act, br in self.hand_buttons():
            if hit(br, x, y):
                if act == "hand:clear":
                    self.hand_strokes = []
                    self.hand_cur = None
                    self.hand_msg = "已清除"
                elif act == "hand:undo":
                    if self.hand_strokes:
                        self.hand_strokes.pop()
                        self.hand_msg = "撤销了一笔"
                    else:
                        self.hand_msg = "没有可撤销的"
                elif act == "hand:bs":
                    self.cur = self.cur[:-1]
                    self.hand_msg = "退格（输入框少一个字）"
                elif act == "hand:recog":
                    self.hand_recognize()
                elif act == "hand:kb":
                    self.set_input_mode(IN_KB)
                return True
        return False

    def hand_begin(self, x, y):
        """落笔：开新的一笔"""
        self.hand_cur = [(x, y)]
        self.hand_msg = ""

    def hand_move(self, x, y):
        """移动：往当前笔迹加点（抽稀，点太密没意义还慢）"""
        if self.hand_cur is None:
            return
        lx, ly = self.hand_cur[-1]
        if abs(x - lx) + abs(y - ly) >= 2:
            self.hand_cur.append((x, y))

    def hand_end(self):
        """抬笔：收笔"""
        if self.hand_cur:
            self.hand_strokes.append(self.hand_cur)
            self.hand_cur = None

    def hand_recognize(self):
        """把笔迹渲染成 PNG -> 百度手写 OCR -> 回填输入框"""
        if not self.hand_strokes:
            self.hand_msg = "画板是空的，先写几个字"
            return

        def fn():
            import io as _io
            import base64 as _b64
            import urllib.parse as _up
            import urllib.request as _u
            try:
                from PIL import Image, ImageDraw
            except Exception as e:
                return "手写失败（没装 PIL）: %s" % e
            try:
                # ① 笔迹 -> 白底黑字 PNG
                xs = [p[0] for st in self.hand_strokes for p in st]
                ys = [p[1] for st in self.hand_strokes for p in st]
                if not xs:
                    return "画板是空的"
                pad = 26
                bx0, bx1 = min(xs) - pad, max(xs) + pad
                by0, by1 = min(ys) - pad, max(ys) + pad
                w, h = max(8, bx1 - bx0), max(8, by1 - by0)
                # ★ 百度要求：最短边 >= 15px，最长边别超 4096
                scale = 1.0
                if min(w, h) < 15:
                    scale = 15.0 / min(w, h)
                if max(w, h) * scale > 1400:
                    scale = 1400.0 / max(w, h)
                W2 = max(15, int(w * scale))
                H2 = max(15, int(h * scale))
                im = Image.new("RGB", (W2, H2), (255, 255, 255))
                d = ImageDraw.Draw(im)
                lw = max(2, int(4 * scale))
                for st in self.hand_strokes:
                    pts = [((px - bx0) * scale, (py - by0) * scale)
                           for px, py in st]
                    if len(pts) >= 2:
                        d.line(pts, fill=(0, 0, 0), width=lw, joint="curve")
                    elif pts:
                        d.ellipse([pts[0][0] - 2, pts[0][1] - 2,
                                   pts[0][0] + 2, pts[0][1] + 2],
                                  fill=(0, 0, 0))
                buf = _io.BytesIO()
                im.save(buf, "PNG")
                png = buf.getvalue()

                # ② 百度 token（和语音共用同一个 key）
                if "/home/zynq" not in sys.path:
                    sys.path.insert(0, "/home/zynq")
                from agent import tts
                tok = tts.token()
                url = ("https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"
                       "?access_token=" + tok)
                body = _up.urlencode(
                    {"image": _b64.b64encode(png).decode()}).encode()
                req = _u.Request(
                    url, data=body,
                    headers={"Content-Type":
                             "application/x-www-form-urlencoded"},
                    method="POST")
                # ★ 用 tts._urlopen —— 它带 CA 兜底（板子系统 CA 不全）
                with tts._urlopen(req, 30) as r:
                    d2 = json.loads(r.read().decode("utf-8", "replace"))
                if d2.get("error_code"):
                    return "手写识别失败: %s %s" % (d2.get("error_code"),
                                                 d2.get("error_msg"))
                words = d2.get("words_result") or []
                text = "".join(str(x.get("words", "")) for x in words)
                if not text:
                    return "没认出来（写大一点、字分开一点再试）"
                # ③ 回填输入框 —— 和键盘/语音同一个缓冲
                self.cur += text
                self.hand_strokes = []
                return "手写识别: %s" % text
            except Exception as e:
                return "手写失败: %s: %s" % (type(e).__name__, e)
        self._bg("hand", fn)
'''
    if anchor_tail in src:
        src = src.replace(anchor_tail, tail_block, 1)
        print("   ✓ 键盘面板收尾 + 语音面板 + 手写面板")
    else:
        print("   ✗ 面板结尾锚点没找到")

    if a.check:
        print("\n （--check 模式，未写文件）")
        return 0
    if src == orig:
        print("\n ★ 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 apps_agent.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
