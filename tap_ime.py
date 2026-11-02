#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tap_ime.py —— 往板载输入法里注入按键，验证拼音->候选->上屏

★ 关键：每次点击必须是**单独的 SSH 命令**。
   之前踩过坑：一条 SSH 里连着写两次 /tmp/ui_tap，后写的会覆盖前一个，
   结果只响应一次点击。

键盘坐标（由布局算出）：
  KB_Y=436, 每行高 27, 间隙 3
  第1行 1234567890   y=449
  第2行 qwertyuiop   y=479
  第3行 asdfghjkl.   y=509
  第4行 zxcvbnm_-/   y=539
  键宽 76 间隙 4，10 键总宽 796，起点 x=114 -> 第 i 个键中心 x = 114+38+i*80
"""
import subprocess
import sys
import time

ROWS = ["1234567890", "qwertyuiop", "asdfghjkl.", "zxcvbnm_-/"]
Y = [449, 479, 509, 539]
X0 = 114 + 38
DX = 80


def key_xy(ch):
    for r, row in enumerate(ROWS):
        if ch in row:
            return X0 + row.index(ch) * DX, Y[r]
    if ch == " ":
        return 200, 569
    return None


def tap(x, y):
    """一次点击 = 一条独立 SSH 命令"""
    r = subprocess.run(
        [sys.executable, "board.py",
         "printf '%d,%d' > /tmp/ui_tap; sleep 0.9; rm -f /tmp/ui_tap"
         % (x, y)],
        capture_output=True, text=True, timeout=90)
    return r.returncode == 0


def type_text(s):
    for ch in s:
        xy = key_xy(ch)
        if not xy:
            print("  [!] 没有键位:", ch)
            continue
        print("  敲 %s -> %s" % (ch, xy))
        tap(*xy)
        time.sleep(0.35)


def main():
    word = sys.argv[1] if len(sys.argv) > 1 else "xianzai"
    print("=== 打字: %s ===" % word)
    type_text(word)
    print("=== 打完，截图看候选 ===")


if __name__ == "__main__":
    main()
