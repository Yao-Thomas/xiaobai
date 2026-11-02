#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_warm.py —— 把【大块背景色】从冷蓝调回暖色

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
2026-10-03 修好了 fbui.py 的像素字节序（BGR;24 -> RGB）之后，
颜色终于正确了，但用户反馈：

    "软件颜色很好，这都不用改，但是整体背景变太蓝了，
     原先那样更好，就是软件不改，你懂吗"

原因很清楚：
    修好之前，显存里的 R/B 是互换的，所以
        设计深蓝 (10,12,22)  →  实际显示成暖棕 (22,12,10)
    用户看到的、并且喜欢的，其实是【那个暖棕色】。
    修好之后背景首次以"设计意图"的深蓝色出现 —— 他觉得太蓝。

所以这个脚本做的事情是：
    ★ 只把【大块背景/底色】的 R 和 B 对调，让它重新呈现暖色
    ★ 彩色按钮、蓝色气泡、绿色开关一律【不动】
      （那些是用户说"很好"的"软件颜色"）

哪些算"背景"：主背景、左侧栏、消息卡片、输入框、设置卡片/遮罩、
              候选栏、键盘底、未选中的条目底色。
哪些【不】动：所有高亮/按钮/气泡/开关的彩色。

用法:
    python patch_warm.py --check     # 只看会改什么
    python patch_warm.py             # 真的改
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_agent.py")

# ── 要调的背景色：(原来的冷蓝) -> (暖色) ──
#   规则：R 和 B 对调，G 不动 —— 明度基本不变，色相从蓝转暖。
#
#   ★ 只列【大块背景】，彩色的一律不在表里。
WARM = [
    # 主背景（全屏 clear）
    ("scr.clear((10, 12, 22))",
     "scr.clear((22, 12, 10))        # ★ 暖色背景（原先是冷蓝 10,12,22）"),
    # 左侧栏
    ("scr.rect([x0, y0, x1, y1], fill=(18, 22, 34))",
     "scr.rect([x0, y0, x1, y1], fill=(34, 22, 18))"),
    # 消息卡片
    ("scr.rrect([x0, y0, x1, y1], 12, fill=(15, 18, 28),",
     "scr.rrect([x0, y0, x1, y1], 12, fill=(28, 18, 15),"),
    # 小白的深灰气泡
    ("fill=(30, 36, 50))", "fill=(50, 36, 30))"),
    # 输入框
    ("scr.rrect(_ir, 8, fill=(20, 26, 44), outline=(70, 100, 160))",
     "scr.rrect(_ir, 8, fill=(44, 26, 20), outline=(160, 100, 70))"),
    # 设置遮罩 + 卡片
    ("scr.rect([0, 62, scr.w, scr.h], fill=(8, 10, 18))",
     "scr.rect([0, 62, scr.w, scr.h], fill=(18, 10, 8))"),
    ("scr.rrect(P, 16, fill=(24, 29, 44), outline=(58, 74, 108), width=2)",
     "scr.rrect(P, 16, fill=(44, 29, 24), outline=(108, 74, 58), width=2)"),
    # 键盘底 + 候选栏
    ("scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(12, 16, 26))",
     "scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(26, 16, 12))"),
    ("scr.rrect(CAND_RECT_KB, 8, fill=(16, 20, 32),",
     "scr.rrect(CAND_RECT_KB, 8, fill=(32, 20, 16),"),
    # 未选中的会话条目
    ("scr.rrect(r, 7, fill=(38, 62, 108) if on else (26, 32, 48))",
     "scr.rrect(r, 7, fill=(38, 62, 108) if on else (48, 32, 26))"),
]

# ── 明确【不】动的（列出来是为了自检）──
KEEP = ["(48, 96, 168)", "(40, 70, 120)", "(38, 62, 108)", "(44, 74, 122)",
        "(40, 78, 132)", "(44, 104, 168)", "(38, 140, 88)", "(40, 90, 150)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src

    print("=" * 70)
    print(" 把大块背景从冷蓝调回暖色")
    print("=" * 70)

    n = 0
    for old, new in WARM:
        c = src.count(old)
        if c == 0:
            print("   ✗ 没匹配到: %s" % old[:52])
            continue
        src = src.replace(old, new)
        n += c
        print("   ✓ (%d 处) %s" % (c, old[:52]))

    print()
    print(" 检查：彩色（软件颜色）有没有被误改")
    for k in KEEP:
        if k not in orig:
            continue
        if k not in src:
            print("   ★ 警告：%s 被改掉了！" % k)
        else:
            print("   ✓ %s 保持不动" % k)

    if a.check:
        print("\n （--check 模式，不写文件）")
        return 0
    if src == orig:
        print("\n ★ 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 %s（共改 %d 处）" % (os.path.basename(P), n))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
