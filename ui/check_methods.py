#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_methods.py —— 检查 desktop.py 里 Desktop 类的方法是否完整"""
import ast

src = open("/home/zynq/ui/desktop.py").read()
tree = ast.parse(src)
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "Desktop":
        ms = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
        print("  Desktop 方法数:", len(ms))
        for m in ("run", "_check_edge_flip", "_do_tap", "_try_start_drag",
                  "draw", "goto_page", "add_page", "move_app", "load_pages",
                  "draw_icon", "_drag_rect", "grid", "slot_at"):
            print("   %-20s %s" % (m, "OK" if m in ms else "★ 缺失!"))
        break
else:
    print("  没找到 Desktop 类!")
