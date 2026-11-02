#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_py.py —— ★ 写 Python 文件后的自动检查

════════════════════════════════════════════════════════════════════
为什么要有这个
════════════════════════════════════════════════════════════════════
我在这个项目里【同一个错犯了三次】：
    在 Python 字符串里用了中文引号（" " ‘ '），
    因为中文引号也是"引号"，Python 会把它当成字符串结束符的一半，
    于是整行 SyntaxError，而且报错位置看起来莫名其妙。

    例：
        print("这里是"点发送"的入口")
                            ↑ Python 认为字符串到这儿就结束了
    报错：SyntaxError: invalid syntax. Perhaps you forgot a comma?

⇒ 每次写完文件都跑一下这个，比等运行时报错快得多。

它查四件事：
    ① 语法（ast.parse）
    ② 字符串里的中文引号（★ 就是上面那个坑）
    ③ 制表符和空格混用
    ④ 文件末尾没有换行

用法:
    python lint_py.py file1.py file2.py ...
    python lint_py.py --all            # 扫工作区里所有 .py
"""
import argparse
import ast
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★★★ 危险的中文引号 = 只有这四个：U+201C / U+201D / U+2018 / U+2019
#
# 为什么 『』「」 不算：
#   那四个（“ ” ‘ ’）和 ASCII 引号是【同一个坑】——
#   在 Python 字符串里它们会让字符串提前结束。
#   而 『』「」 是【书名号/角括号】，Python 完全不当引号，
#   所以我专门用它们来替代 —— 出现在代码里是【故意的】，不该报。
#
# ★ 注意这里的写法：下面两行必须用【真正的转义序列】\uXXXX，
#   不能写成字面量 u201c —— 那样 CN_QUOTES 会变成字符串 "u201c..."
#   然后 any(q in s ...) 里的 q 是单个字符 'u'，任何含 u 的行都会误报。
#   （这个坑我自己刚踩过一次：PowerShell 的 Replace 把 \ 变成了 \\）
CN_QUOTES = "\u201c\u201d\u2018\u2019"
SAFE_QUOTES = "\u300c\u300d\u300e\u300f"

# 只在这些扩展名里查中文引号（文档、注释里用中文引号是正常的）
CODE_EXT = (".py", ".sh", ".tcl")


def lint(path):
    """返回 (ok, [问题...])"""
    problems = []
    try:
        raw = io.open(path, encoding="utf-8").read()
    except Exception as e:
        return False, ["读不了: %s" % e]

    # ① 语法
    if path.endswith(".py"):
        try:
            ast.parse(raw)
        except SyntaxError as e:
            problems.append("语法错误 第 %s 行: %s" % (e.lineno, e.msg))

    # ② ★ 中文引号 —— ★ 已改成【只在我自己新写的代码里预警】，
    #    不再当成错误（2026-10-03 修误报）
    #
    # ────────────────────────────────────────────────────────────────
    # ★★★ 为什么要把这条降级
    # 当初加这条检查，是因为我【三次】写代码时犯了这个错：
    #     scr.text(..., "点"发送"按钮", ...)      ← ASCII 引号嵌 ASCII 引号
    # 那确实会让 Python 把字符串提前截断。
    #
    # 但我把检测条件写成了"行里出现 U+201C/U+201D 就算错" —— 这是错的：
    #     scr.text(..., "点“返回”回桌面", ...)    ← 合法！能正常 parse
    # 因为 U+201C/U+201D 是【非 ASCII 字符】，在 Python 字符串里
    # 就是普通字符，跟 'a'、'中' 一样，根本不会截断。
    #
    # 结果：apps_about / apps_mines / apps_net / apps_sys 四个文件
    #       被误报了，我差点去"修"它们（改坏反而更糟）。
    #
    # ⇒ 真正的语法错误 ast.parse 已经能抓到（第 ① 项），
    #   所以这条改成【提示】而不是【错误】，只提醒我自己留意。
    # ────────────────────────────────────────────────────────────────
    cn_hits = []
    lines = raw.split("\n")
    in_doc = False
    for i, ln in enumerate(lines, 1):
        s = ln
        if s.strip().startswith("#"):
            continue
        n3 = s.count('"""') + s.count("'''")
        if in_doc:
            if n3:
                in_doc = False
            continue
        if n3 % 2 == 1:
            in_doc = True
            continue
        if any(q in s for q in CN_QUOTES):
            stripped = s.strip()
            looks_code = (stripped.startswith(("print(", "return", "if ", "elif ",
                                               "while ", "for ", "def ", "self.",
                                               "raise ", "yield ", "assert "))
                          or "=" in s or "(" in s)
            if looks_code:
                bad = [q for q in CN_QUOTES if q in s]
                cn_hits.append("第 %d 行有中文引号 %s（合法，仅提示）: %s"
                               % (i, "".join(bad), stripped[:60]))
    # ★ 不加入 problems（bool(problems) 决定成败）

    # ③ 制表符
    for i, ln in enumerate(lines, 1):
        if "\t" in ln:
            problems.append("第 %d 行有制表符（和空格混用会缩进错）" % i)
            break

    # ④ 末尾换行
    if raw and not raw.endswith("\n"):
        problems.append("文件末尾没有换行")

    return (not problems), problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    files = list(a.files)
    if a.all:
        here = os.path.dirname(os.path.abspath(__file__))
        for root, dirs, fs in os.walk(here):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "build", "dist", "node_modules",
                                    "ai_delivery", "vm2", "atk2026",
                                    "cnn_hls_2026", "_qt", "craft_dl",
                                    "scope_policy_deliv", "eq_policy_deliv",
                                    "rag_kb", "agent")]
            for f in fs:
                if f.endswith(CODE_EXT):
                    files.append(os.path.join(root, f))

    if not files:
        print("没给文件")
        return 1

    bad = 0
    for p in files:
        if not os.path.exists(p):
            print("  ✗ %s 不存在" % p)
            bad += 1
            continue
        ok, probs = lint(p)
        if ok:
            if not a.quiet:
                print("  ✓ %s" % os.path.basename(p))
        else:
            bad += 1
            print("  ✗ %s" % os.path.basename(p))
            for pr in probs[:6]:
                print("      %s" % pr)
    print()
    print("  %d 个文件，%d 个有问题" % (len(files), bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
