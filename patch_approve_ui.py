#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_approve_ui.py —— 把"批准/拒绝"做进 Agent App 界面

背景：权限层（policy.py）会把危险动作放进"待批准队列"，
      但只能在 API 上调，用户在板子上没法点。这个补丁补上界面。

设计：候选栏原本两种模式（有拼音->候选字 / 没拼音->常用指令），
      加**第三种**：有待批准动作时优先显示：

        [!] 同意? touch /tmp/x     [同意] [拒绝] [全部拒绝]

      不额外占屏幕空间，也不用新开页面。

（本脚本用三引号写代码块 —— 之前用转义拼接把字符串拆断了。）
"""
import io
import sys

P = "ui/apps_agent.py"
src = io.open(P, encoding="utf-8").read()

if "self.pending" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

done = []

# ─────────────────── 1) __init__ 加状态
old = "        self.quick = 0          # 常用指令滚动位置"
new = old + """
        # ★ 待批准的危险动作（来自 Agent 权限层 /pending）
        self.pending = []
        self._pend_t = 0.0"""
assert old in src, "init 锚点"
src = src.replace(old, new, 1)
done.append("状态")

# ─────────────────── 2) pump 轮询 + _approve
old = '''    def pump(self):
        while True:
            try:
                name, res = self.q.get_nowait()
            except queue.Empty:
                return
            self.busy = ""
            self.out(res)
'''
new = '''    def pump(self):
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
'''
assert old in src, "pump 锚点"
src = src.replace(old, new, 1)
done.append("pump轮询+_approve")

# ─────────────────── 3) bar_items 加批准模式
old = '''        items = []
        x = CAND_RECT[0] + 6
        y0, y1 = CAND_RECT[1] + 4, CAND_RECT[3] - 4
        h = y1 - y0
        # 左侧：模式切换
        mw = 66
'''
new = '''        items = []
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
'''
assert old in src, "bar_items 锚点"
src = src.replace(old, new, 1)
done.append("批准模式")

# ─────────────────── 4) 绘制：批准条样式
old = '''        for i, (label, act, r) in enumerate(items):
            if act == "mode":
'''
new = '''        for i, (label, act, r) in enumerate(items):
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
'''
assert old in src, "绘制锚点"
src = src.replace(old, new, 1)
done.append("批准条绘制")

# ─────────────────── 5) 提示文字
old = '''        hint = ("打拼音选字" if not self.py else
                "空格上屏首个 · 退格删字母")
'''
new = '''        if self.pending:
            hint = "小白想做上面的操作，等你点头"
        elif not self.py:
            hint = "打拼音选字"
        else:
            hint = "空格上屏首个 · 退格删字母"
'''
assert old in src, "提示锚点"
src = src.replace(old, new, 1)
done.append("提示文字")

# ─────────────────── 6) 事件处理
old = '''                hitbar = True
                if act == "mode":
'''
new = '''                hitbar = True
                if act == "none":
                    pass
                elif act.startswith("approve:"):
                    _, rid, okf = act.split(":")
                    app._approve(rid, okf == "1")
                elif act == "mode":
'''
assert old in src, "事件锚点"
src = src.replace(old, new, 1)
done.append("事件处理")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成:", " / ".join(done))
print("syntax OK")
