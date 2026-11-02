#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_run_split.py —— 修好 run() / _handle_click 的拆分

════════════════════════════════════════════════════════════════════
背景：为了治手写"划斜线变折线"，我把 run() 改成【事件批处理】：
        一帧把队列里所有事件都吃光，再统一重绘一次
      （原来一帧只取一个事件，手指划快了就丢点）。

改的时候把点击逻辑整块搬进 _handle_click()，但搬得不干净：
  · 2388-2438 留了一段坏头部（if True: if True:）+ 重复的语音/手写处理
  · 2440-2645 是真正的点击逻辑，里面全是 continue（函数里没有循环，
    本来应该是 return）
  · 2646-2652 还留着原来 run() 结尾的 time.sleep 和退出兜底（重复）

这个脚本做外科修复：
  ① 删掉坏头部和重复的语音/手写段
  ② 把真正的点击逻辑接成 _handle_click 的函数体
  ③ 其中的 continue -> return
  ④ 缩进从 12 空格降到 4 空格
  ⑤ 删掉重复的 run() 结尾

用法:
    python fix_run_split.py --check
    python fix_run_split.py
"""
import argparse
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "apps_agent.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    lines = io.open(P, encoding="utf-8").read().split("\n")
    orig = list(lines)
    print("=" * 70)
    print(" 修 run() / _handle_click 的拆分")
    print("=" * 70)

    def find(pred, start=0):
        for i in range(start, len(lines)):
            if pred(lines[i]):
                return i
        return -1

    # ── 定位 ──
    i_func = find(lambda s: s.startswith("def _handle_click("))
    if i_func < 0:
        print("   ✗ 找不到 _handle_click")
        return 1
    i_real = find(lambda s: s.strip() == "if back_hit(x, y):", i_func)
    if i_real < 0:
        print("   ✗ 找不到真正的点击逻辑起点")
        return 1
    # 真正的点击逻辑结束：下一个 "        time.sleep(0.03)"
    i_tail = find(lambda s: s == "        time.sleep(0.03)", i_real)
    if i_tail < 0:
        print("   ✗ 找不到点击逻辑结尾")
        return 1

    print("   _handle_click 在行 %d" % (i_func + 1))
    print("   真正点击逻辑 %d ~ %d" % (i_real + 1, i_tail))
    print("   结尾垃圾 %d ~ %d" % (i_tail + 1, len(lines)))

    # ── 取出真正的点击逻辑 ──
    body = lines[i_real:i_tail]

    # 缩进：原来 12 空格 -> 4 空格（去掉 8 个空格）
    out = []
    for ln in body:
        if ln.startswith("        "):          # 12 空格
            out.append(ln[8:])
        elif ln.strip() == "":
            out.append("")
        else:
            out.append(ln)                      # 注释等

    # continue -> return（函数体里没有循环）
    fixed = []
    n_ret = 0
    for ln in out:
        s = ln.strip()
        if s == "continue":
            indent = ln[:len(ln) - len(ln.lstrip())]
            fixed.append(indent + "return")
            n_ret += 1
        else:
            # 行尾的 "continue" 也要换
            if re.search(r"\bcontinue\b", ln):
                ln = re.sub(r"\bcontinue\b", "return", ln)
                n_ret += 1
            fixed.append(ln)

    # ── 组装 ──
    head = [
        'def _handle_click(app, scr, x, y):',
        '    """处理一次真正的「点击」（up / tap）',
        '',
        '    ★ 2026-10-03 从 run() 里整块搬出来：run() 现在要做【事件批处理】',
        '      （一帧把队列里所有事件吃光，治手写"划斜线变折线"），',
        '      点击逻辑就抽成这个函数。逻辑一行没改，只是把 continue 换成了',
        '      return —— 因为它现在不在循环里了。',
        '    """',
    ]
    new_lines = lines[:i_func] + head + fixed + [""]

    print("   ✓ 删掉坏头部和重复的语音/手写段")
    print("   ✓ 点击逻辑缩进 12 -> 4 空格")
    print("   ✓ continue -> return（%d 处）" % n_ret)
    print("   ✓ 删掉重复的 run() 结尾")

    if a.check:
        print("\n （--check 模式，未写文件）")
        return 0
    io.open(P, "w", encoding="utf-8").write("\n".join(new_lines))
    print("\n 已写回 apps_agent.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
