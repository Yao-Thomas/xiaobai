#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_layout.py —— 把 apps_agent.py 里的固定坐标换成动态坐标

════════════════════════════════════════════════════════════════════
为什么键盘弹出时坐标要变
════════════════════════════════════════════════════════════════════
用户报的 bug：
    "有时候在键盘输入，键盘会退掉；有时候没有开键盘会输入"

根因是键盘和输入框【位置重叠】：
    键盘  KB_Y=400，键高 30，间隔 4
      行1 400-430   行2 434-464   行3 468-498   行4 502-532
    输入框 IN_RECT = 474-510      ← ★ 和行3、行4 重叠

run() 里又是【先判输入框】再判键盘，
⇒ 点键盘第 3 行会被输入框抢走，把 kb_open 翻成 False（键盘消失）

这个脚本把三处改成动态：
    ① layout() / draw_bubbles() 用 log_rect(kb_open)
    ② draw() 的输入框用 rect_in(scr, kb_open)
    ③ bar_items() 用当前候选栏矩形

用法:
    python patch_layout.py            # 打补丁
    python patch_layout.py --check    # 只看会改什么
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

# (说明, 旧文本, 新文本)
PATCHES = [
    ("layout() 用动态消息区",
     "        x0, y0, x1, y1 = LOG_RECT\n        pad = 10",
     "        # ★ 动态消息区：键盘弹出时会被压扁\n"
     "        x0, y0, x1, y1 = log_rect(getattr(self, \"kb_open\", False))\n"
     "        pad = 10"),

    ("draw_bubbles() 用动态消息区",
     "        x0, y0, x1, y1 = LOG_RECT\n        scr.rrect(LOG_RECT, 10,",
     "        _lr = log_rect(getattr(self, \"kb_open\", False))\n"
     "        x0, y0, x1, y1 = _lr\n        scr.rrect(_lr, 10,"),

    ("bar_items 的右边界用当前候选栏",
     "if x + w > CAND_RECT[2] - 8:",
     "if x + w > _cr[2] - 8:"),

    ("draw() 的输入框用 rect_in",
     "        scr.rrect(IN_RECT, 8, fill=(20, 26, 44), outline=(70, 100, 160))",
     "        _ir = rect_in(scr, self.kb_open)\n"
     "        scr.rrect(_ir, 8, fill=(20, 26, 44), outline=(70, 100, 160))"),

    ("输入框文字 x 用 _ir",
     "        scr.text((IN_RECT[0] + 10, (IN_RECT[1] + IN_RECT[3]) // 2),",
     "        scr.text((_ir[0] + 10, (_ir[1] + _ir[3]) // 2),"),

    ("输入框右侧提示 x 用 _ir",
     "        scr.text((IN_RECT[2] - 10, (IN_RECT[1] + IN_RECT[3]) // 2),",
     "        scr.text((_ir[2] - 10, (_ir[1] + _ir[3]) // 2),"),

    ("键盘弹出时候选栏用 CAND_RECT_KB",
     "            scr.rrect(CAND_RECT, 8, fill=(16, 20, 32), outline=(52, 62, 88))",
     "            scr.rrect(CAND_RECT_KB, 8, fill=(16, 20, 32),\n"
     "                      outline=(52, 62, 88))"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 70)
    print(" 把固定坐标换成动态坐标")
    print("=" * 70)

    n_ok = 0
    for desc, old, new in PATCHES:
        cnt = src.count(old)
        if cnt == 0:
            print("   ✗ %-34s 没匹配到" % desc)
            continue
        if cnt > 1:
            print("   ! %-34s 匹配到 %d 处（只改第一处）" % (desc, cnt))
        src = src.replace(old, new, 1)
        n_ok += 1
        print("   ✓ %-34s 改了" % desc)

    if a.check:
        print("\n （--check 模式，不写文件）")
        return 0
    if src == orig:
        print("\n ★ 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 %s（改了 %d 处）" % (os.path.basename(P), n_ok))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
