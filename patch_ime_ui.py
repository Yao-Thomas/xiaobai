#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_ime_ui.py —— 给 apps_agent.py 加本地拼音输入法

改动：
  1) 布局：输入框上移，中间插一条「候选栏」，键盘压缩一点点塞进去
  2) AgentApp 加载 ime_cn.IME，维护拼音缓冲 self.py
  3) 拼音模式下字母进缓冲，候选栏实时出候选；点候选上屏
  4) ★ 缓冲为空时候选栏显示「常用指令」大按钮（点一下就问）
  5) 模式切换 拼音/英文
"""
import io
import sys

P = "ui/apps_agent.py"
src = io.open(P, encoding="utf-8").read()

if "ime_cn" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ---------- 1) 布局常量 ----------
old = """LOG_RECT = [36, 108, 988, 356]
IN_RECT = [36, 362, 988, 400]
BTN_Y = 70
BTN_H = 32
KB_Y = 406"""
new = """LOG_RECT = [36, 108, 988, 346]
IN_RECT = [36, 352, 988, 388]        # 输入框（已上屏的文字）
CAND_RECT = [36, 392, 988, 430]      # ★ 候选栏 / 常用指令栏
BTN_Y = 70
BTN_H = 32
KB_Y = 436                           # 键盘（压缩过，给候选栏腾地方）
KB_KH = 27
KB_GAP = 3

# 常用指令：拼音缓冲为空时显示在候选栏上，点一下就发
QUICK = ["现在几点", "今天天气", "播放音乐", "你好", "介绍一下你自己",
         "停止播放", "看一看时间"]"""
assert old in src, "布局锚点没找到"
src = src.replace(old, new, 1)

# ---------- 2) __init__ 状态 ----------
old = """        self.kb = MiniKeyboard(y0=KB_Y, key_w=76, key_h=32, gap=4)"""
new = """        self.kb = MiniKeyboard(y0=KB_Y, key_w=76, key_h=KB_KH, gap=KB_GAP)
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
        self.quick = 0          # 常用指令滚动位置"""
assert old in src, "kb 锚点没找到"
src = src.replace(old, new, 1)

# ---------- 3) 拼音相关方法（插在 buttons 之前）----------
old = """    # ---- 绘制 ----
    def buttons(self, scr):"""
new = """    # ---- 拼音输入 ----
    def refresh_cands(self):
        \"\"\"重算候选。缓冲为空 -> 用常用指令填满候选栏\"\"\"
        if not self.pinyin:
            self.cands = []
            return
        if self.py and self.ime and self.ime.ok:
            self.cands = self.ime.candidates(self.py, limit=8)
        else:
            self.cands = []

    def commit(self, text):
        \"\"\"把候选/指令上屏，清掉拼音缓冲\"\"\"
        self.cur += text
        self.py = ""
        self.refresh_cands()

    def commit_first(self):
        \"\"\"空格/回车：优先上屏第一个候选，没有候选就把字母原样上屏\"\"\"
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
        \"\"\"返回候选栏上要画的东西 [(文本, 动作, 矩形)]

        有拼音缓冲 -> 候选字/词；没有 -> 常用指令
        \"\"\"
        items = []
        x = CAND_RECT[0] + 6
        y0, y1 = CAND_RECT[1] + 4, CAND_RECT[3] - 4
        h = y1 - y0
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
    def buttons(self, scr):"""
assert old in src, "buttons 锚点没找到"
src = src.replace(old, new, 1)

# ---------- 4) draw：输入框 + 候选栏 ----------
old = """        scr.rrect(IN_RECT, 8, fill=(20, 26, 44), outline=(70, 100, 160))
        scr.text((IN_RECT[0] + 10, (IN_RECT[1] + IN_RECT[3]) // 2),
                 "> " + self.cur[-74:] + "_", 19, (230, 240, 255),
                 anchor="lm", cn=True)
        self.kb.draw(scr)"""
new = """        scr.rrect(IN_RECT, 8, fill=(20, 26, 44), outline=(70, 100, 160))
        shown = "> " + self.cur[-70:]
        if self.py:
            shown += "  [ " + self.py + " ]"
        scr.text((IN_RECT[0] + 10, (IN_RECT[1] + IN_RECT[3]) // 2),
                 shown + "_", 19, (230, 240, 255), anchor="lm", cn=True)

        # ★ 候选栏 / 常用指令栏
        scr.rrect(CAND_RECT, 8, fill=(16, 20, 32), outline=(52, 62, 88))
        items = self.bar_items(scr)
        for i, (label, act, r) in enumerate(items):
            if act == "mode":
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
        hint = ("打拼音选字" if not self.py else
                "空格上屏首个 · 退格删字母")
        scr.text((CAND_RECT[2] - 8, (CAND_RECT[1] + CAND_RECT[3]) // 2),
                 hint, 14, (120, 135, 165), anchor="rm", cn=True)

        self.kb.draw(scr)"""
assert old in src, "draw 锚点没找到"
src = src.replace(old, new, 1)

# ---------- 5) run：事件处理 ----------
old = """            k = app.kb.press(x, y)
            if k is not None:
                if k == "<BS>":
                    app.cur = app.cur[:-1]
                elif k == "<ENTER>":
                    if app.cur.strip() and not app.busy:
                        app.out("我> " + app.cur)
                        app.ask(app.cur.strip())
                        app.cur = ""
                else:
                    app.cur += k"""
new = """            # ★ 先看候选栏（候选字 / 常用指令 / 模式切换）
            hitbar = False
            for label, act, r in app.bar_items(scr):
                if not hit(r, x, y):
                    continue
                hitbar = True
                if act == "mode":
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
                        app.cur += k"""
assert old in src, "run 锚点没找到"
src = src.replace(old, new, 1)

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
