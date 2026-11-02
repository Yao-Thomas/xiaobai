#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_bar_wysiwyg.py —— 修"绘制态与命中态不一致"

═══ 上轮那个 bug ═══
点了「同意」但那条动作没被 resolve 掉（重发同命令返回的还是同一个 id）。

═══ 根因（设计层面）═══
run() 里是这样的：

    app.draw(scr, btns)              # 画的时候用 self.pending = [A]
    scr.flush()
    ev = touch.poll()                # 用户点
    for label, act, r in app.bar_items(scr):   # ★ 又渲染了一遍！
        if hit(r, x, y): ...

命中测试用的是**重新渲染**的结果。只要这两次之间 self.pending 变了
（pump 每 2 秒刷新一次），看到的和点到的就不是同一条。

═══ 修法 ═══
让 draw() 把**画出来的那份 items 原样存下来**（self.bar_rendered），
run() 只对这份做命中测试 —— 所见即所点（WYSIWYG）。

顺带修一个隐患：_bg() 在 busy 时**静默 return**，调用者不知道没执行。
改成返回 bool。
"""
import io
import sys

P = "ui/apps_agent.py"
src = io.open(P, encoding="utf-8").read()

if "bar_rendered" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

done = []

# ─────────────────── 1) __init__ 加"画出来的那一份"
old = """        self.pending = []
        self._pend_t = 0.0"""
new = """        self.pending = []
        self._pend_t = 0.0
        # ★ 屏幕上**实际画出来**的候选栏/批准栏条目。
        #   点击只跟这份对，避免"画的"和"点的"不是同一份。
        self.bar_rendered = []"""
assert old in src, "init 锚点"
src = src.replace(old, new, 1)
done.append("bar_rendered 状态")

# ─────────────────── 2) draw() 里存下来
old = """        items = self.bar_items(scr)
        for i, (label, act, r) in enumerate(items):"""
new = """        items = self.bar_items(scr)
        self.bar_rendered = items          # ★ 存下来给点击用
        for i, (label, act, r) in enumerate(items):"""
assert old in src, "draw 锚点"
src = src.replace(old, new, 1)
done.append("draw 存 items")

# ─────────────────── 3) run() 命中测试改用 bar_rendered
old = """            for label, act, r in app.bar_items(scr):
                if not hit(r, x, y):
                    continue"""
new = """            # ★ 只对**屏幕上画出来的那一份**做命中测试（所见即所点）
            for label, act, r in app.bar_rendered:
                if not hit(r, x, y):
                    continue"""
assert old in src, "命中锚点"
src = src.replace(old, new, 1)
done.append("命中用 bar_rendered")

# ─────────────────── 4) _bg 返回 bool
old = """    def _bg(self, name, fn):"""
if old in src:
    # 找到 _bg 的完整函数体
    i = src.find(old)
    j = src.find("\n    def ", i + 10)
    if j == -1:
        j = len(src)
    body = src[i:j]
    if "return False" not in body:
        # if self.busy: return  ->  return False
        body2 = body.replace("        if self.busy:\n            return\n",
                             "        if self.busy:\n"
                             "            return False      # ★ 上一件事还没做完\n")
        # 函数结尾加 return True
        body2 = body2.rstrip() + "\n        return True\n\n"
        src = src[:i] + body2 + src[j:]
        done.append("_bg 返回 bool")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成:", " / ".join(done))
print("syntax OK")
