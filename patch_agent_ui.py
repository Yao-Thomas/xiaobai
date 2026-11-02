#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_agent_ui.py —— 把 Agent App 的消息区改成**气泡式**（参考 Harness 界面）

用户原话："AGENT 做的太粗糙，你至少也要参考你自己 Harness 的页面设计吧"

改动：
  1) 消息从纯文本行 -> (角色, 文字) 的**气泡**
       user 右对齐蓝色 / bot 左对齐深灰带头像 / sys 居中灰字小号
  2) **中文自动换行**（中文没空格，必须逐字量宽）
  3) 从**底部往上**排版，最新的一条永远可见
  4) bot 气泡带一个圆形头像（和 Harness 一样有身份感）
  5) "正在思考" 用三个跳动的点，而不是一行文字
  6) 气泡圆角 + 内边距 + 最大宽度 62%（像手机聊天）

兼容性：out() 仍然是入口，内部按前缀判断角色，所以原来所有调用都不用改。
"""
import io
import sys

P = "ui/apps_agent.py"
src = io.open(P, encoding="utf-8").read()

if "draw_bubbles" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ─────────────────────────────── 1) __init__ 换成消息列表
old = '''        self.lines = ["我是系统管家小白 —— 这块板子的系统管家。",'''
new = '''        # ★ 消息改成 (角色, 文字)：user=我说的 / bot=小白说的 / sys=系统提示
        self.msgs = [("bot", "我是系统管家小白 —— 这块板子的系统管家。"),
                     ("sys", "打字后按回车问我；也可以点「听」用说的。")]
        self.lines = ["我是系统管家小白 —— 这块板子的系统管家。",'''
assert old in src, "init 锚点没找到"
src = src.replace(old, new, 1)

# ─────────────────────────────── 2) out() 同时维护 msgs
old_out = src[src.find("    def out(self, s):"):src.find("    def _bg(self, name, fn):")]
new_out = '''    def out(self, s):
        """加一条消息。按前缀判断角色（保持旧调用不变）。"""
        for raw in str(s).split("\\n"):
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
            if ch == "\\n":
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

'''
src = src.replace(old_out, new_out, 1)
print("  OK: 气泡排版 + 自动换行 + 输入指示")

# ─────────────────────────────── 3) draw() 里换成 draw_bubbles
old_d = '''        scr.rrect(LOG_RECT, 8, fill=(6, 8, 16), outline=(50, 70, 110))
        maxl = (LOG_RECT[3] - LOG_RECT[1] - 14) // 21
        y = LOG_RECT[1] + 7
        for ln in self.lines[-maxl:]:
            col = (255, 235, 190) if ln.startswith(("小白>", "错误")) else \\
                  (170, 220, 255) if ln.startswith(("我", "正在", "听到", "自检")) else \\
                  (185, 230, 190)
            scr.text((LOG_RECT[0] + 10, y), ln, 17, col, cn=True)
            y += 21
'''
new_d = '''        self.draw_bubbles(scr)
'''
if old_d in src:
    src = src.replace(old_d, new_d, 1)
    print("  OK: draw() 改用气泡")
else:
    print("  [!] draw() 的消息区没匹配到，手工确认")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")
