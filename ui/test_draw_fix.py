#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_draw_fix.py —— 画板"笔画莫名连起来"的回归测试
  场景: 画一笔 -> 抬笔 -> 在别处再落笔
  期望: 两笔之间【不能】有一条横跨的线
做法: 拦截 ImageDraw.line, 记录所有线段, 检查有没有跨越两笔之间的长线
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import PIL.ImageDraw as ID

segments = []
_real_line = ID.ImageDraw.line


def fake_line(self, xy, **kw):
    try:
        segments.append((tuple(xy[0]), tuple(xy[1])))
    except Exception:
        pass
    return _real_line(self, xy, **kw)


ID.ImageDraw.line = fake_line


class FakeScreen(__import__("test_ui_local").FakeScreen):
    """复用 test_ui_local 里已经调好的假屏幕"""
    pass


class ScriptedTouch:
    """按脚本吐事件"""
    def __init__(self, events):
        self.events = list(events)
        self.n = 0

    def poll(self, move=False):
        self.n += 1
        if not self.events or self.n > 500:
            raise SystemExit(0)          # 脚本用完 -> 结束应用
        return self.events.pop(0)


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    return bool(cond)


def main():
    fails = 0
    print("=" * 62)
    print(" 画板: 笔画不应该连起来 (回归测试)")
    print("=" * 62)

    # ---- 脚本: 第1笔在左上, 抬笔, 第2笔在右下 ----
    C = (52, 68)      # 画布左上角
    ev = [
        ("down", C[0] + 60,  C[1] + 60),
        ("move", C[0] + 90,  C[1] + 90),
        ("move", C[0] + 120, C[1] + 120),
        ("up",   C[0] + 120, C[1] + 120),
        # ---- 抬笔后隔一会儿, 在远处落笔 ----
        ("down", C[0] + 700, C[1] + 320),
        ("move", C[0] + 730, C[1] + 350),
        ("up",   C[0] + 730, C[1] + 350),
    ]

    import apps_draw, fbui
    # 让 back_hit 别误触发
    fbui.back_hit = lambda x, y: False

    segments.clear()
    scr = FakeScreen()
    touch = ScriptedTouch(ev)
    try:
        apps_draw.run(scr, touch)
    except SystemExit:
        pass

    print("  记录到 %d 条线段" % len(segments))
    for a, b in segments:
        print("     %s -> %s" % (a, b))

    # 检查: 有没有一条线段横跨两笔(长度 > 200)
    long_ones = []
    for a, b in segments:
        dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
        if max(dx, dy) > 200:
            long_ones.append((a, b, max(dx, dy)))

    fails += 0 if check(not long_ones,
                        "没有跨笔的长线段 (最长 %d)" %
                        max([max(abs(a[0]-b[0]), abs(a[1]-b[1])) for a, b in segments] or [0])) else 1

    if long_ones:
        for a, b, d in long_ones:
            print("     ❌ 发现长线: %s -> %s (%d 像素)" % (a, b, d))

    # 检查: 每笔内部的线段是存在的(说明确实画了)
    short_ok = any(max(abs(a[0]-b[0]), abs(a[1]-b[1])) <= 60 for a, b in segments)
    fails += 0 if check(short_ok, "笔画内部的短线段正常") else 1

    print("")
    print("=" * 62)
    print(" ✅ 全部通过!" if fails == 0 else " ❌ %d 项失败" % fails)
    print("=" * 62)
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
