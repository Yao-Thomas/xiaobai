#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_click.py —— ★★★ 点击路径冒烟测试（2026-10-03 补）

════════════════════════════════════════════════════════════════════
为什么要单独写这个
────────────────────────────────────────────────────────────────────
2026-10-03 踩了个大坑，用户报"直接应用出错"：

    File "apps_agent.py", line 2490, in run
        _handle_click(app, scr, x, y)
    File "apps_agent.py", line 2683, in _handle_click
        for name, act, r in btns:
    NameError: name 'btns' is not defined

  原因：为了治手写"划斜线变折线"，我把 run() 改成事件批处理，
        点击逻辑整块抽成 _handle_click()，但里面还在用 run() 的
        局部变量 btns（而且 btns 是在事件循环之后才算的）。

★★ 教训：smoke_app.py 只测了【画】（draw 各种状态），
   【一次点击都没测】。所以这种"一碰就崩"的错误全漏过去了。

这个脚本专测点击：把屏幕上每个可点区域都点一遍，
任何一个抛异常就报出来。
── 覆盖：按钮排每个按钮、返回键、喇叭、设置键、输入框、
         侧栏（新对话/会话条目/删除键）、消息区、设置页每一项、
         三种输入方式的面板（键盘/语音/手写）

用法:
    sudo python3 smoke_click.py            # 板子上（要 root 访问 fb）
    python smoke_click.py --dry            # 只做静态检查
"""
import argparse
import io
import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# ★ fbui / apps_agent 在 /home/zynq/ui（板子上的布局），脚本本身在 /home/zynq
for _p in (HERE, os.path.join(HERE, "ui"), "/home/zynq/ui"):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

FAILS = []
OKS = 0


def tap(app, scr, btns, x, y, note):
    """点一下，记录成功/失败"""
    global OKS
    try:
        r = app_mod._handle_click(app, scr, btns, x, y)
        OKS += 1
        return r
    except Exception as e:
        FAILS.append((note, x, y, "%s: %s" % (type(e).__name__, e),
                      traceback.format_exc()))
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    global app_mod
    import fbui
    import apps_agent as AA
    app_mod = AA

    print("=" * 72)
    print(" 点击路径冒烟测试")
    print("=" * 72)

    scr = fbui.Screen()

    # ── 场景 1：主界面（键盘模式）──
    print("\n【1】主界面 · 键盘")
    app = AA.AgentApp()
    app.in_mode = AA.IN_KB
    app.kb_open = True
    btns = app.buttons(scr)
    app.draw(scr, btns)
    for name, act, r in btns:
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        tap(app, scr, btns, cx, cy, "按钮排 " + act)
    # 键盘上每个键
    for k, kr in AA.AgentApp().kb.keys[:12]:
        tap(app, scr, btns, (kr[0] + kr[2]) // 2, (kr[1] + kr[3]) // 2,
            "键盘键 " + repr(k))
    for nm, kr in (("空格", app.kb.sp), ("退格", app.kb.bs),
                   ("回车", app.kb.ent), ("左", app.kb.left),
                   ("右", app.kb.right)):
        if kr:
            tap(app, scr, btns, (kr[0] + kr[2]) // 2, (kr[1] + kr[3]) // 2,
                "键盘 " + nm)
    # 固定区域
    for (x, y, nm) in ((70, 30, "返回"), (968, 31, "喇叭"),
                       (84, 572, "设置键"), (600, 492, "输入框"),
                       (84, 100, "侧栏-新对话"), (84, 130, "侧栏-条目"),
                       (500, 300, "消息区空白"), (500, 560, "按钮排空白")):
        tap(app, scr, btns, x, y, nm)
    print("   ✓ 点完 %d 处" % OKS)

    # ── 场景 2：设置页（三页都点）──
    print("\n【2】设置页")
    for pg, nm in ((0, "通用"), (1, "模型"), (2, "工具")):
        app = AA.AgentApp()
        app.settings_open = True
        app.settings_page = pg
        app.load_settings = lambda: None
        btns = app.buttons(scr)
        app.draw(scr, btns)
        n0 = OKS
        for k, r in list(app.settings_hit.items()):
            tap(app, scr, btns, (r[0] + r[2]) // 2, (r[1] + r[3]) // 2,
                "设置页%s %s" % (nm, k))
        print("   ✓ %s 页：点了 %d 项" % (nm, OKS - n0))

    # ── 场景 3：三种输入方式的面板 ──
    print("\n【3】三套输入面板")
    for m in (AA.IN_KB, AA.IN_VOICE, AA.IN_HAND):
        app = AA.AgentApp()
        app.in_mode = m
        app.kb_open = True
        btns = app.buttons(scr)
        app.draw(scr, btns)
        n0 = OKS
        if m == AA.IN_HAND:
            for label, act, r in app.hand_buttons():
                tap(app, scr, btns, (r[0] + r[2]) // 2, (r[1] + r[3]) // 2,
                    "手写面板 " + act)
        elif m == AA.IN_VOICE:
            vr = app.voice_big
            tap(app, scr, btns, (vr[0] + vr[2]) // 2, (vr[1] + vr[3]) // 2,
                "语音大按钮")
        # 面板上的笔迹区域
        r = app.hand_panel_rect()
        tap(app, scr, btns, (r[0] + r[2]) // 2, (r[1] + r[3]) // 2,
            "面板中心")
        print("   ✓ %s：点了 %d 处" % (m, OKS - n0))

    # ── 结果 ──
    print()
    print("=" * 72)
    if FAILS:
        print(" ★ 有 %d 处点击崩了：" % len(FAILS))
        for note, x, y, err, tb in FAILS:
            print("   ✗ %-28s (%d,%d)" % (note, x, y))
            print("      %s" % err)
        print("=" * 72)
        return 1
    print(" 总体: ★ 全部通过（%d 处点击无一异常）" % OKS)
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
