#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""breakdown_ui.py —— 把 UI 绘制成本拆到函数级（离屏，不写显存）"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch
import apps_scope_dual as A

scr = Screen()
scr.flush = lambda box=None: None
touch = Touch()

app = A.App(scr)
app.make_bg()
for _ in range(60):
    app.step()
    time.sleep(0.004)


def bench(fn, n=40):
    fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000.0


print("=== 各绘制函数单独耗时（离屏）===")
print("  %-24s %8s" % ("函数", "ms/次"))
print("  " + "-" * 34)
for name, fn in (
    ("step（采集+统计）", app.step),
    ("draw_wave", app.draw_wave),
    ("draw_stat（两行参数）", app.draw_stat),
    ("draw_top（顶栏）", app.draw_top),
    ("draw_scales（刻度）", app.draw_scales),
    ("draw_cards（五张卡）", app.draw_cards),
    ("draw_ctl（控制行）", app.draw_ctl),
):
    print("  %-24s %8.2f" % (name, bench(fn)))

print()
print("=== 拆 draw_stat 内部 ===")
# 分别量：PIL 画文字 / to_raw / blit_raw
import ctypes
box = [0, A.ST1[1], A.W, A.ST1[3]]
print("  %-34s %8.2f" % ("scr.img.crop(box)", bench(lambda: scr.img.crop(box))))
c = scr.img.crop(box)
print("  %-34s %8.2f" % ("scr.to_raw(crop)", bench(lambda: scr.to_raw(c))))
raw = scr.to_raw(c)
print("  %-34s %8.2f" % ("scr.blit_raw(全宽36行)",
                         bench(lambda: scr.blit_raw(0, A.ST1[1], A.W, 36, raw))))
print("  %-34s %8.2f" % ("scr.img.paste(bg.crop(box))",
                         bench(lambda: scr.img.paste(app.bg.crop(box), (0, A.ST1[1])))))


def txt_cn():
    scr.text((100, 60), "12.34V", 16, (255, 255, 255), cn=True, bold=True)


def txt_en():
    scr.text((100, 60), "12.34V", 16, (255, 255, 255), cn=False)


def txt_label():
    scr.text((100, 60), "垂直位置", 12, (200, 200, 200), cn=True)


print()
print("=== 文字渲染本身 ===")
print("  %-34s %8.2f" % ("text 数字(cn=True)", bench(txt_cn, 60)))
print("  %-34s %8.2f" % ("text 数字(cn=False)", bench(txt_en, 60)))
print("  %-34s %8.2f" % ("text 中文标签(cn=True)", bench(txt_label, 60)))

print()
print("=== 颜色变换是否拖慢（Screen 有色彩补偿）===")
try:
    print("  色彩补偿:", getattr(scr, "_cc", "n/a"))
except Exception:
    pass

print()
print("BKD_DONE")
