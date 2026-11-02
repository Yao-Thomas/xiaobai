#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deblue_apps.py —— 把所有 App 的【蓝色背景】改成苹果中性灰

════════════════════════════════════════════════════════════════════
问题
════════════════════════════════════════════════════════════════════
用户："你的服务卡片怎么全是蓝的，我要灰色的，或者正常点的，你可以参考苹果"
      "但是点开设置还是蓝的，你改了吗？"

    ⇒ 每个 App 文件都有自己的内联调色板，全是深蓝色系。
      home.py 我改了，apps_settings.py 等一大堆还没改。

难点
════════════════════════════════════════════════════════════════════
不能无脑把所有颜色都变灰 —— 那会把【强调色】也毁掉：
    蓝色按钮 / 绿色开关 / 红色警告 / 橙色高亮  这些都是该保留的。

判据（用饱和度区分）：
    sat = max(r,g,b) - min(r,g,b)

    · sat < SAT_MAX 且 b > r   → 低饱和偏蓝 = 背景/描边/次要文字 → 转中性灰
    · sat >= SAT_MAX           → 高饱和 = 强调色 → 保留原样

中性灰怎么算：
    lum = 0.299*r + 0.587*g + 0.114*b     (感知亮度，ITU-R BT.601)
    neutral = (lum, lum, lum)
    ★ 只改色相、不改明暗 ⇒ 界面的层次感（谁亮谁暗）完全不变。

用法:
    python deblue_apps.py --list          # 只列出会改哪些，不动文件
    python deblue_apps.py                 # 真的改
    python deblue_apps.py --sat 50        # 改判据（默认 40）
"""
import argparse
import glob
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ★ 排除：fbui.py（底层库，已单独处理）、以及工具脚本
EXCLUDE = ("fbui.py", "desktop.py", "home.py", "patch_", "lint_", "smoke_",
           "verify_", "test_", "show_", "render_", "calib_", "temp_calib",
           "color_probe", "touch_inject", "bench_", "deblue")

COLOR_RE = re.compile(r"\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)")


def to_neutral(r, g, b):
    """低饱和偏蓝 -> 中性灰（保留感知亮度）"""
    lum = int(0.299 * r + 0.587 * g + 0.114 * b)
    return (lum, lum, lum)


def is_blueish_bg(r, g, b, sat_max):
    """判断一个颜色是不是"低饱和的蓝色背景"

    ★★★ 判据要卡准（第一版就卡错了）
    ────────────────────────────────────────────────────────────
    第一版只看了 sat<40 且 b>r，结果：
        (36, 62, 52)  sat=26, b=52>r=36  →  被判成"偏蓝"改了灰
        ★ 但它明明是个【深绿色】！最大通道是 G(62)。
        同样中招的还有 (20,52,38)、(28,60,44) —— 全是绿调。

    正确判据要三条同时满足：
        ① 蓝通道是【最大】的          b == max(r,g,b)
        ② 蓝比红明显高               b - r > 15
        ③ 饱和度低（不是鲜艳的强调蓝）  sat < sat_max
    ────────────────────────────────────────────────────────────
    """
    if b != max(r, g, b):
        return False          # ★ 最大通道不是蓝 -> 不是蓝调（可能是绿/黄/红）
    if b - r <= 8:
        return False          # ★ 蓝只比红高一点点 -> 基本中性了，别动
                              #   阈值取 8：中性灰 (58,58,60) 差 2、(44,44,46) 差 2、
                              #   (99,99,102) 差 3 都能正确排除；
                              #   而设置页那个背景 (18,20,30) 差 12 会被正确抓到。
                              #   （原来取 15 太严，(18,20,30) 漏掉了）
    sat = max(r, g, b) - min(r, g, b)
    return sat < sat_max


def scan(path, sat_max):
    """返回 [(行号, 原颜色, 新颜色, 整行内容)]"""
    out = []
    for i, ln in enumerate(io.open(path, encoding="utf-8"), 1):
        for m in COLOR_RE.finditer(ln):
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if max(r, g, b) > 255:
                continue
            if is_blueish_bg(r, g, b, sat_max):
                out.append((i, (r, g, b), to_neutral(r, g, b), ln.rstrip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只看不改")
    ap.add_argument("--sat", type=int, default=40,
                    help="饱和度阈值（默认 40，越大改得越多）")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(HERE, "apps_*.py")))
    files = [f for f in files
             if not any(e in os.path.basename(f) for e in EXCLUDE)]

    print("=" * 74)
    print(" 把各 App 的蓝色背景改成苹果中性灰（饱和度阈值 %d）" % a.sat)
    print("=" * 74)
    print("  规则：sat < %d 且 b > r  ->  转中性灰（保留感知亮度）"
          % a.sat)
    print("        饱和度高 -> 强调色，原样保留")
    print()

    total_files = 0
    total_hits = 0
    for p in files:
        hits = scan(p, a.sat)
        if not hits:
            continue
        total_files += 1
        total_hits += len(hits)
        name = os.path.basename(p)
        # 去重后展示
        uniq = {}
        for i, old, new, ln in hits:
            uniq.setdefault(old, [new, 0, i])
            uniq[old][1] += 1
        print("── %s  (%d 处，%d 种颜色) ──" % (name, len(hits), len(uniq)))
        for old, (new, cnt, firstline) in sorted(uniq.items(),
                                                 key=lambda kv: -kv[1][1]):
            print("   %2d 次  (%3d,%3d,%3d) -> (%3d,%3d,%3d)"
                  % (cnt, old[0], old[1], old[2], new[0], new[1], new[2]))
        print()

    if a.list:
        print(" 共 %d 个文件、%d 处（--list 模式，未修改）"
              % (total_files, total_hits))
        return 0

    # 真正替换
    for p in files:
        src = io.open(p, encoding="utf-8").read()

        def repl(m):
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if is_blueish_bg(r, g, b, a.sat):
                n = to_neutral(r, g, b)
                return "(%d, %d, %d)" % n
            return m.group(0)

        new = COLOR_RE.sub(repl, src)
        if new != src:
            io.open(p, "w", encoding="utf-8").write(new)

    print(" ✓ 已修改 %d 个文件、%d 处" % (total_files, total_hits))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
