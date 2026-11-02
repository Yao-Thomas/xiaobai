#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_board_up.py —— 修 board_up.py 里把 run() 返回值当字符串用的 bug

board.py::run() 返回 (out, err) 元组，不是字符串。
"""
import io
import re

P = "board_up.py"
src = io.open(P, encoding="utf-8").read()

if "def route(" in src:
    print("已修过")
    raise SystemExit(0)

# 插入一个只返回 stdout 的辅助函数，并把它替换掉所有 board.run(...) 调用
helper = '''

def route(cmd, timeout=180):
    """board.run 返回 (out, err) 元组；这里只要 stdout 字符串。"""
    out, _ = board.run(cmd, timeout=timeout, quiet=True)
    return out

'''
src = src.replace("def hr(t):", helper.lstrip("\n") + "\ndef hr(t):", 1)

# board.run(  -> route(    （只替换调用，不替换定义）
src = re.sub(r"\bboard\.run\(", "route(", src)
# 上面会把 import board 那行以外的地方都换掉；确认 import 还在
assert "import board" in src, "import board 丢了"

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("修好了, syntax OK")
print("剩余 board.run 调用:", src.count("board.run("))
print("route( 调用:", src.count("route("))
