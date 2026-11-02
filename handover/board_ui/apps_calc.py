#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_calc.py —— 触摸计算器"""
import time
from fbui import header, back_hit, btn, hit, font

KEYS = [
    ["C", "(", ")", "/"],
    ["7", "8", "9", "*"],
    ["4", "5", "6", "-"],
    ["1", "2", "3", "+"],
    ["0", ".", "<-", "="],
]
COLORS = {
    "C": (168, 56, 56), "=": (46, 150, 90), "<-": (140, 96, 40),
    "/": (60, 96, 160), "*": (60, 96, 160), "-": (60, 96, 160), "+": (60, 96, 160),
    "(": (60, 96, 160), ")": (60, 96, 160),
}

def layout(scr):
    x0, y0 = 60, 190
    w, h = (scr.w - 120 - 3 * 14) // 4, 68
    rects = {}
    for r, row in enumerate(KEYS):
        for c, k in enumerate(row):
            x = x0 + c * (w + 14)
            y = y0 + r * (h + 14)
            rects[k] = [x, y, x + w, y + h]
    return rects

def draw(scr, expr, result, msg):
    scr.clear((22, 22, 22))
    header(scr, "计算器")
    # 显示区
    scr.rrect([60, 74, scr.w - 60, 174], 14, fill=(14, 14, 14), outline=(60, 90, 150), width=2)
    scr.text((scr.w - 80, 148), expr[-32:] if expr else "0", 34, (243, 243, 243),
             anchor="rs", mono=True)
    if result is not None:
        scr.text((scr.w - 80, 98), "= " + str(result), 26, (120, 230, 170), anchor="rs", mono=True)
    elif msg:
        scr.text((80, 98), msg, 22, (255, 160, 120), cn=True, anchor="ls")
    # 键盘
    for k, r in layout(scr).items():
        lbl = "←" if k == "<-" else k
        btn(scr, r, lbl, fill=COLORS.get(k, (54, 68, 104)), size=30, bold=True, radius=12)
    scr.text((scr.w // 2, 175 + 5 * 82 + 30), "提示: 支持 + - * / ( ) 和小数点",
             17, (110, 130, 170), cn=True, anchor="mm")

def run(scr, touch):
    expr, result, msg = "", None, ""
    while True:
        draw(scr, expr, result, msg)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            for k, r in layout(scr).items():
                if hit(r, x, y):
                    msg = ""
                    if k == "C":
                        expr, result = "", None
                    elif k == "<-":
                        expr = expr[:-1]
                        result = None
                    elif k == "=":
                        try:
                            if expr and all(c in "0123456789.+-*/() " for c in expr):
                                result = eval(expr)
                                if isinstance(result, float) and result == int(result):
                                    result = int(result)
                            else:
                                msg = "表达式不合法"
                        except ZeroDivisionError:
                            msg, result = "除零错误", None
                        except Exception:
                            msg, result = "算式有误", None
                    else:
                        expr += k
                        result = None
                    break
            print("计算器:", repr(expr), result, msg)
        time.sleep(0.03)
