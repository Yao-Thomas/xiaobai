#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_warm2.py —— 把顶栏和桌面的背景也调回暖色

════════════════════════════════════════════════════════════════════
为什么还要改这一轮
════════════════════════════════════════════════════════════════════
上一轮（patch_warm.py）只改了 apps_agent.py 里的大块背景，
用户反馈"改了吗？没变化啊" —— 查下来是漏了两处【最大的蓝色块】：

  ① fbui.py 的 header()   ← 所有 App 的顶栏（0~62 那条）
        header(scr, title, accent=(70,110,180), bg=(30,40,68), cn=True)
        这两个默认值是深蓝，所有 App 共用。

  ② desktop.py 的调色板   ← 整个桌面（卡片首页、任务栏、图标）
        C_TOP / C_BOT / C_TASKBAR / C_ICON_BG / C_LINE ... 全是蓝的

修法同上一轮：
    ★ 只把【背景/底色类】的 R 和 B 对调（明度不变，色相转暖）
    ★ 强调色（高亮蓝、文字白）一律不动 —— 那是用户说"很好"的软件颜色

用法:
    python patch_warm2.py --check
    python patch_warm2.py
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

# ── fbui.py：顶栏默认色 ──
FBUI = [
    ("def header(scr, title, accent=(70, 110, 180), bg=(30, 40, 68), cn=True):",
     "# ★ 默认色已调暖（原 accent=(70,110,180) bg=(30,40,68) 是冷蓝）\n"
     "def header(scr, title, accent=(180, 110, 70), bg=(68, 40, 30), cn=True):"),
    ("scr.rect([0, 0, scr.w, 60], fill=bg)",
     "scr.rect([0, 0, scr.w, 60], fill=bg)"),
    ('btn(scr, [10, 8, 130, 52], "< 返回", fill=(60, 70, 100), size=22, cn=True)',
     'btn(scr, [10, 8, 130, 52], "< 返回", fill=(100, 70, 60), size=22, cn=True)'),
]

# ── desktop.py：背景类调色板（R<->B 对调）──
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

# ── 明确保留的强调色 ──
KEEP_DESK = ["C_ICON_PR  = (120, 170, 255)", "C_ACCENT   = (86, 166, 255)",
             "C_TEXT     = (238, 243, 255)", "C_TEXT_DIM = (148, 166, 200)"]


def patch(path, table, label, check):
    p = os.path.join(HERE, path)
    src = io.open(p, encoding="utf-8").read()
    orig = src
    print("── %s ──" % label)
    n = 0
    for old, new in table:
        c = src.count(old)
        if c == 0:
            print("   ✗ 没匹配到: %s" % old[:56])
            continue
        src = src.replace(old, new)
        n += c
        mark = "（无变化）" if old == new else ""
        print("   ✓ (%d 处) %s %s" % (c, old[:52], mark))
    if not check and src != orig:
        io.open(p, "w", encoding="utf-8").write(src)
        print("   → 已写回 %s（%d 处）" % (path, n))
    elif src == orig:
        print("   → 没有可改的")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    print("=" * 70)
    print(" 顶栏 + 桌面的背景调回暖色")
    print("=" * 70)
    print()

    patch("fbui.py", FBUI, "fbui.py  顶栏默认色", a.check)
    patch("desktop.py", DESK, "desktop.py  桌面调色板", a.check)

    print(" 保留的强调色（软件颜色）检查：")
    ds = io.open(os.path.join(HERE, "desktop.py"), encoding="utf-8").read()
    for k in KEEP_DESK:
        print("   %s %s" % ("✓" if k in ds else "✗ 丢了", k))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
