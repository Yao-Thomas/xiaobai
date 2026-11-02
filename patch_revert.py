#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_revert.py —— 回退我之前【擅自改的】那三处颜色

════════════════════════════════════════════════════════════════════
为什么要回退
════════════════════════════════════════════════════════════════════
事情经过：
  1. 修好 fbui 的字节序（BGR;24 → RGB）后，颜色终于正确
  2. 用户说"软件颜色很好，这都不用改，但是整体背景变太蓝了"
     —— 我理解成"把背景色改成暖色"
  3. 于是改了 apps_agent.py 的背景色（patch_warm.py）
  4. 用户说"改了吗？没变化啊" —— 因为顶栏是 fbui 画的，我没改
  5. 于是又改了 fbui 的 header() 和 desktop.py（patch_warm2.py）
  6. 用户："还有就是我没让你改APP的啊"

★ 正解：面板偏蓝是【硬件特性】，补偿要放在【共享底层 fbui】里，
  一处修好所有界面，任何 App 的颜色定义一个字都不用动。
  这个已经在 fbui.py 的 ColorDraw 里做好了（绘制时变换颜色，零开销）。

所以之前那三处"改颜色"的改动是【多余的、位置也错的】，
而且会和底层补偿叠加（两次补偿 = 过校正）。全部回退。

回退内容：
  ① apps_agent.py  —— 11 处背景色从暖色改回原来的冷蓝设计值
  ② desktop.py     —— 9 个调色板常量改回去
  ③ fbui.py header —— 默认配色改回 (70,110,180) / (30,40,68)

★ 注意：fbui 的字节序修复（RGB）和色温补偿必须【保留】，不在回退范围内。

用法:
    python patch_revert.py --check
    python patch_revert.py
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

# ── ① apps_agent.py：暖色 -> 原设计值 ──
APPS = [
    ("scr.clear((22, 12, 10))        # ★ 暖色背景（原先是冷蓝 10,12,22）",
     "scr.clear((10, 12, 22))"),
    ("scr.rect([x0, y0, x1, y1], fill=(34, 22, 18))",
     "scr.rect([x0, y0, x1, y1], fill=(18, 22, 34))"),
    ("scr.rrect([x0, y0, x1, y1], 12, fill=(28, 18, 15),",
     "scr.rrect([x0, y0, x1, y1], 12, fill=(15, 18, 28),"),
    ("fill=(50, 36, 30))", "fill=(30, 36, 50))"),
    ("scr.rrect(_ir, 8, fill=(44, 26, 20), outline=(160, 100, 70))",
     "scr.rrect(_ir, 8, fill=(20, 26, 44), outline=(70, 100, 160))"),
    ("scr.rect([0, 62, scr.w, scr.h], fill=(18, 10, 8))",
     "scr.rect([0, 62, scr.w, scr.h], fill=(8, 10, 18))"),
    ("scr.rrect(P, 16, fill=(44, 29, 24), outline=(108, 74, 58), width=2)",
     "scr.rrect(P, 16, fill=(24, 29, 44), outline=(58, 74, 108), width=2)"),
    ("scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(26, 16, 12))",
     "scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(12, 16, 26))"),
    ("scr.rrect(CAND_RECT_KB, 8, fill=(32, 20, 16),",
     "scr.rrect(CAND_RECT_KB, 8, fill=(16, 20, 32),"),
    ("scr.rrect(r, 7, fill=(38, 62, 108) if on else (48, 32, 26))",
     "scr.rrect(r, 7, fill=(38, 62, 108) if on else (26, 32, 48))"),
]

# ── ② desktop.py：暖色 -> 原调色板 ──
DESK = [
    ("C_TOP      = (86, 44, 30)", "C_TOP      = (30, 44, 86)"),
    ("C_BOT      = (20, 9, 7)", "C_BOT      = (7, 9, 20)"),
    ("C_TASKBAR1 = (54, 30, 22)", "C_TASKBAR1 = (22, 30, 54)"),
    ("C_TASKBAR2 = (36, 19, 14)", "C_TASKBAR2 = (14, 19, 36)"),
    ("C_LINE     = (140, 84, 56)", "C_LINE     = (56, 84, 140)"),
    ("C_ICON_BG  = (118, 66, 44)", "C_ICON_BG  = (44, 66, 118)"),
    ("C_ICON_BG2 = (156, 92, 62)", "C_ICON_BG2 = (62, 92, 156)"),
    ("C_MENU_BG  = (48, 27, 20)", "C_MENU_BG  = (20, 27, 48)"),
    ("C_MENU_HD  = (108, 62, 44)", "C_MENU_HD  = (44, 62, 108)"),
]

# ── ③ fbui.py header：暖色 -> 原默认值 ──
FBUI = [
    ("# ★ 默认色已调暖（原 accent=(70,110,180) bg=(30,40,68) 是冷蓝）\n"
     "def header(scr, title, accent=(180, 110, 70), bg=(68, 40, 30), cn=True):",
     "def header(scr, title, accent=(70, 110, 180), bg=(30, 40, 68), cn=True):"),
    ('btn(scr, [10, 8, 130, 52], "< 返回", fill=(100, 70, 60), size=22, cn=True)',
     'btn(scr, [10, 8, 130, 52], "< 返回", fill=(60, 70, 100), size=22, cn=True)'),
]


def patch(path, table, label, check):
    p = os.path.join(HERE, path)
    if not os.path.exists(p):
        print("── %s ──  ★ 文件不在本地，跳过" % label)
        return
    src = io.open(p, encoding="utf-8").read()
    orig = src
    print("── %s ──" % label)
    n = 0
    for old, new in table:
        c = src.count(old)
        if c == 0:
            print("   ✗ 没匹配到: %s" % old[:50])
            continue
        src = src.replace(old, new)
        n += c
        print("   ✓ (%d 处) %s" % (c, old[:50]))
    if not check and src != orig:
        io.open(p, "w", encoding="utf-8").write(src)
        print("   → 已写回（%d 处）" % n)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    print("=" * 70)
    print(" 回退「擅自改的」三处颜色（保留字节序修复 + 色温补偿）")
    print("=" * 70)
    print()
    patch("apps_agent.py", APPS, "apps_agent.py  背景色", a.check)
    patch("desktop.py", DESK, "desktop.py  调色板", a.check)
    patch("fbui.py", FBUI, "fbui.py  header 默认色", a.check)

    # 自检：该保留的还在不在
    fb = io.open(os.path.join(HERE, "fbui.py"), encoding="utf-8").read()
    print(" 自检（必须保留的）：")
    checks = [
        ('self.mode = {24: "RGB", 32: "RGBA"}', "字节序修复 RGB"),
        ("class ColorDraw", "ColorDraw 色温补偿代理"),
        ("self.COMP_B = 12", "蓝通道偏置 12"),
    ]
    for pat, name in checks:
        print("   %s %s" % ("✓" if pat in fb else "★ 丢了", name))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
