#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_apple.py —— 卡片改成苹果风中性灰 + 补齐卡片点击

════════════════════════════════════════════════════════════════════
用户反馈（两条）
════════════════════════════════════════════════════════════════════
1) "你的服务卡片怎么全是蓝的，我要灰色的，或者正常点的，你可以参考苹果"
   → 卡片首页是 home.py 画的（不是 desktop.py），调色板是深蓝。
     换成苹果深色模式的【中性灰】。

   苹果官方深色模式色值（用这个，不要自己调）：
       systemBackground (dark)             #000000
       secondarySystemBackground (dark)    #1C1C1E  (28,28,30)
       tertiarySystemBackground (dark)     #2C2C2E  (44,44,46)
       systemGray5 (dark)                  #2C2C2E
       systemGray4 (dark)                  #3A3A3C  (58,58,60)
       secondaryLabel (dark)               ≈ (152,152,157)
       tertiaryLabel (dark)                ≈ (104,104,109)
       systemBlue    (dark)                #0A84FF  (10,132,255)
       systemGreen   (dark)                #30D158  (48,209,88)
       systemOrange  (dark)                #FF9F0A  (255,159,10)

2) "底下的服务卡片不能点击进相关软件"
   → desktop.py 的 card_action() 只处理了 system/network/weather/music，
     "clock" 和 "recent" 掉进 else: return —— 点了完全没反应。
     补齐：clock -> 打开「时钟」App。

用法:
    python patch_apple.py --check
    python patch_apple.py
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

# ── ① home.py：深蓝 -> 苹果中性灰 ──
HOME = [
    ("C_BG_TOP = (22, 30, 52)", "C_BG_TOP = (28, 28, 30)        # #1C1C1E"),
    ("C_BG_BOT = (8, 11, 22)", "C_BG_BOT = (18, 18, 20)        # 更暗一档"),
    ("C_CARD_TOP = (40, 50, 78)", "C_CARD_TOP = (44, 44, 46)      # #2C2C2E"),
    ("C_CARD_BOT = (18, 24, 40)", "C_CARD_BOT = (28, 28, 30)      # #1C1C1E"),
    ("C_TEXT = (240, 245, 255)", "C_TEXT = (245, 245, 247)"),
    ("C_TEXT_DIM = (150, 166, 198)", "C_TEXT_DIM = (152, 152, 157)"),
    ("C_TEXT_FAINT = (104, 120, 150)", "C_TEXT_FAINT = (104, 104, 109)"),
    ("C_ACCENT = (76, 141, 246)      # #4C8DF6",
     "C_ACCENT = (10, 132, 255)       # #0A84FF  苹果系统蓝"),
    ("C_OK = (52, 199, 89)           # #34C759",
     "C_OK = (48, 209, 88)            # #30D158"),
    ("C_BAR_BG = (44, 54, 78)", "C_BAR_BG = (58, 58, 60)        # #3A3A3C"),
    # 卡片边框也是蓝的，一起中性化
    ("outline=(70, 86, 120)", "outline=(72, 72, 74)"),
]

# ── ② desktop.py：补齐 clock 卡片的动作 ──
DECK = [
    ('''        elif key == "music":
            self.dock_action("music")
            return
        else:
            return''',
     '''        elif key == "music":
            self.dock_action("music")
            return
        elif key == "clock":
            # ★ 补：原来 clock 掉进 else: return，点时钟卡片完全没反应
            a = self.by_name("时钟")
        elif key == "recent":
            # ★ 补：最近使用卡片本身 -> 打开「全部应用」页
            #   （卡片上的 4 个图标走 ("app", 名字)，那条路本来就是好的）
            self.menu_open = True
            self.draw()
            return
        else:
            return'''),
]


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
            print("   ✗ 没匹配到: %s" % old.replace("\n", " | ")[:56])
            continue
        src = src.replace(old, new)
        n += c
        print("   ✓ (%d 处) %s" % (c, old.replace("\n", " | ")[:56]))
    if not check and src != orig:
        io.open(p, "w", encoding="utf-8").write(src)
        print("   → 已写回（%d 处）" % n)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    print("=" * 70)
    print(" 卡片改苹果中性灰 + 补齐卡片点击")
    print("=" * 70)
    print()
    patch("home.py", HOME, "① home.py  调色板 -> 苹果中性灰", a.check)
    patch("desktop.py", DECK, "② desktop.py  card_action 补 clock/recent",
          a.check)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
