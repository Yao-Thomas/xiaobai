#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_original_look.py —— 把【背景】改回暖棕红（原先的观感），图标保持正常

════════════════════════════════════════════════════════════════════
用户到底要什么（我绕了好几轮才捋清楚）
════════════════════════════════════════════════════════════════════
原话：
    "你全改回原先配色，除了软件及其图标"

    "原先配色"   = 我修 BGR->RGB 之前那个观感。
                   那时候 fbui 用 "BGR;24" 写显存，整个屏幕 R/B 互换，
                   所以深蓝背景显示成暖棕红 —— 用户喜欢的是那个。
    "除了软件及其图标" = 软件 UI 元素（按钮/气泡/开关）和图标的颜色
                   保持【正确】的值（该蓝的蓝）。

★ 我上一轮做错了：把配色"回退到设计值"（冷蓝），
  而用户要的是"回到原先的观感"（暖棕红）⇒ 用户："还是蓝的"。

正确的目标 = 背景类颜色换成暖色 + 软件/图标颜色不动。

涉及的四处：
    ① apps_agent.py  —— App 的大块背景
    ② desktop.py     —— 桌面调色板（背景类，不含 C_ACCENT / C_ICON_PR）
    ③ fbui.py header —— 顶栏默认色
    ④ ★ 壁纸         —— 桌面最大的视觉面积，是张图片，
                        调色板改不到它，必须单独做暖色处理

用法:
    python patch_original_look.py --check
    python patch_original_look.py
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

# ── ① apps_agent.py：冷蓝 -> 暖棕红 ──
APPS = [
    ("scr.clear((10, 12, 22))",
     "scr.clear((22, 12, 10))        # ★ 暖色背景（原先观感）"),
    ("scr.rect([x0, y0, x1, y1], fill=(18, 22, 34))",
     "scr.rect([x0, y0, x1, y1], fill=(34, 22, 18))"),
    ("scr.rrect([x0, y0, x1, y1], 12, fill=(15, 18, 28),",
     "scr.rrect([x0, y0, x1, y1], 12, fill=(28, 18, 15),"),
    ("fill=(30, 36, 50))", "fill=(50, 36, 30))"),
    ("scr.rrect(_ir, 8, fill=(20, 26, 44), outline=(70, 100, 160))",
     "scr.rrect(_ir, 8, fill=(44, 26, 20), outline=(160, 100, 70))"),
    ("scr.rect([0, 62, scr.w, scr.h], fill=(8, 10, 18))",
     "scr.rect([0, 62, scr.w, scr.h], fill=(18, 10, 8))"),
    ("scr.rrect(P, 16, fill=(24, 29, 44), outline=(58, 74, 108), width=2)",
     "scr.rrect(P, 16, fill=(44, 29, 24), outline=(108, 74, 58), width=2)"),
    ("scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(12, 16, 26))",
     "scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(26, 16, 12))"),
    ("scr.rrect(CAND_RECT_KB, 8, fill=(16, 20, 32),",
     "scr.rrect(CAND_RECT_KB, 8, fill=(32, 20, 16),"),
    ("scr.rrect(r, 7, fill=(38, 62, 108) if on else (26, 32, 48))",
     "scr.rrect(r, 7, fill=(38, 62, 108) if on else (48, 32, 26))"),
]

# ── ② desktop.py：只换背景类，保留强调色 ──
DESK = [
    ("C_TOP      = (30, 44, 86)", "C_TOP      = (86, 44, 30)"),
    ("C_BOT      = (7, 9, 20)", "C_BOT      = (20, 9, 7)"),
    ("C_TASKBAR1 = (22, 30, 54)", "C_TASKBAR1 = (54, 30, 22)"),
    ("C_TASKBAR2 = (14, 19, 36)", "C_TASKBAR2 = (36, 19, 14)"),
    ("C_LINE     = (56, 84, 140)", "C_LINE     = (140, 84, 56)"),
    ("C_ICON_BG  = (44, 66, 118)", "C_ICON_BG  = (118, 66, 44)"),
    ("C_ICON_BG2 = (62, 92, 156)", "C_ICON_BG2 = (156, 92, 62)"),
    ("C_MENU_BG  = (20, 27, 48)", "C_MENU_BG  = (48, 27, 20)"),
    ("C_MENU_HD  = (44, 62, 108)", "C_MENU_HD  = (108, 62, 44)"),
]

# ── ③ fbui.py：顶栏 + 加一个 warm_image() 给壁纸用 ──
FBUI_HEADER = [
    ("def header(scr, title, accent=(70, 110, 180), bg=(30, 40, 68), cn=True):",
     "# ★ 默认色改成暖色（原先观感）；原值 accent=(70,110,180) bg=(30,40,68)\n"
     "def header(scr, title, accent=(180, 110, 70), bg=(68, 40, 30), cn=True):"),
    ('btn(scr, [10, 8, 130, 52], "< 返回", fill=(60, 70, 100), size=22, cn=True)',
     'btn(scr, [10, 8, 130, 52], "< 返回", fill=(100, 70, 60), size=22, cn=True)'),
]

WARM_FUNC = '''

# ══════════════════════════════════════════════════════════════════════
#  ★★★ 壁纸调暖（2026-10-03）
# ══════════════════════════════════════════════════════════════════════
# 用户要"整体背景回到原先的暖棕红观感"，但桌面最大的视觉面积是【壁纸】，
# 而壁纸是一张图片（scrimg.paste 贴上去的），改调色板常量根本碰不到它。
#
# 所以单独给壁纸加一个暖色处理：把蓝通道压下来、红通道提一点。
# ★ 只作用于壁纸，【不影响图标和软件的颜色】—— 这正是用户的要求
#   （"除了软件及其图标"）。
#
# ★ 原则（一定要分清，不然会双重处理）：
#     资源图（壁纸、从文件加载的图片）  -> warm_image() 调暖
#     屏幕缓存（scr.img.copy() 存的）  -> 已经是调暖后的，不要再处理
# ══════════════════════════════════════════════════════════════════════
WARM_B_DROP = 30      # 蓝通道压低多少
WARM_R_ADD = 14       # 红通道提高多少


def warm_image(im, b_drop=None, r_add=None):
    """把一张【资源图】调暖（降蓝、提红）。只用于壁纸这类背景图。"""
    b_drop = WARM_B_DROP if b_drop is None else b_drop
    r_add = WARM_R_ADD if r_add is None else r_add
    if b_drop == 0 and r_add == 0:
        return im
    if im.mode != "RGB":
        im = im.convert("RGB")
    r, g, b = im.split()
    r = r.point([min(255, v + r_add) for v in range(256)])
    b = b.point([max(0, v - b_drop) for v in range(256)])
    return Image.merge("RGB", (r, g, b))

'''


def patch(path, table, label, check):
    p = os.path.join(HERE, path)
    if not os.path.exists(p):
        print("── %s ──  ★ 文件不在，跳过" % label)
        return
    src = io.open(p, encoding="utf-8").read()
    orig = src
    print("── %s ──" % label)
    n = 0
    for old, new in table:
        c = src.count(old)
        if c == 0:
            print("   ✗ 没匹配到: %s" % old[:52])
            continue
        src = src.replace(old, new)
        n += c
        print("   ✓ (%d 处) %s" % (c, old[:52]))
    if not check and src != orig:
        io.open(p, "w", encoding="utf-8").write(src)
        print("   → 已写回（%d 处）" % n)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    print("=" * 70)
    print(" 背景改回暖棕红（原先观感），软件/图标不动")
    print("=" * 70)
    print()
    patch("apps_agent.py", APPS, "① apps_agent.py  背景", a.check)
    patch("desktop.py", DESK, "② desktop.py  背景类调色板", a.check)
    patch("fbui.py", FBUI_HEADER, "③ fbui.py  顶栏", a.check)

    # ④ fbui.py 里插入 warm_image()
    p = os.path.join(HERE, "fbui.py")
    src = io.open(p, encoding="utf-8").read()
    if "def warm_image(" not in src:
        anchor = "# ---------------- 屏幕 ----------------"
        if anchor in src:
            src = src.replace(anchor, WARM_FUNC + "\n" + anchor, 1)
            if not a.check:
                io.open(p, "w", encoding="utf-8").write(src)
            print("── ④ fbui.py  加 warm_image() ──")
            print("   ✓ 已插入")
        else:
            print("   ✗ 找不到插入点")
    else:
        print("── ④ fbui.py  warm_image() ──")
        print("   （已存在，跳过）")
    print()

    # ⑤ desktop.py 的壁纸出口调用 warm_image
    p = os.path.join(HERE, "desktop.py")
    src = io.open(p, encoding="utf-8").read()
    old = "        import fbui\n        return fbui.comp_image(self._load_wallpaper_raw())"
    new = "        import fbui\n        # ★ 壁纸调暖（背景要回到原先的暖色观感；只动背景图，不动图标）\n        return fbui.warm_image(self._load_wallpaper_raw())"
    if old in src:
        src = src.replace(old, new)
        if not a.check:
            io.open(p, "w", encoding="utf-8").write(src)
        print("── ⑤ desktop.py  壁纸出口调暖 ──")
        print("   ✓ 已改")
    elif "fbui.warm_image(self._load_wallpaper_raw())" in src:
        print("── ⑤ desktop.py  壁纸出口 ──")
        print("   （已是 warm_image，跳过）")
    else:
        print("── ⑤ desktop.py  壁纸出口 ──")
        print("   ✗ 没匹配到，需要手工看 load_wallpaper")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
