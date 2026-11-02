#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_undef.py —— 静态检查：函数里有没有用到【未定义】的名字

════════════════════════════════════════════════════════════════════
为什么要写这个
────────────────────────────────────────────────────────────────────
2026-10-03 踩了个大坑：
  为了治手写"划斜线变折线"，我把 run() 改成事件批处理，
  并把点击逻辑整块抽成 _handle_click(app, scr, x, y)。
  但那个函数里还在用 run() 的局部变量 `btns`，而 btns 是在事件
  循环【之后】才算的 —— 于是：

      NameError: name 'btns' is not defined
      ⇒ 一打开 App 就"应用出错"（用户报的）

  lint_py.py 只做 ast.parse（查语法）+ 语法级检查，
  【查不出这种"名字没定义"】—— 因为它是合法的 Python 语法。

  这个脚本补上这一环：遍历每个函数的 AST，
  找出"读取了一个既不是局部、也不是模块级、也不是内置"的名字。

用法:
    python check_undef.py apps_agent.py desktop.py home.py
    python check_undef.py            # 默认查常用几个
"""
import ast
import builtins
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = ["apps_agent.py", "desktop.py", "home.py", "fbui.py",
           "apps_settings.py", "cloud_api.py"]


def module_names(tree):
    """模块级可见的名字"""
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        out.add(sub.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.If):
            for sub in ast.walk(n):
                if isinstance(sub, (ast.Assign, ast.FunctionDef)):
                    for s2 in ast.walk(sub):
                        if isinstance(s2, ast.Name) and isinstance(s2.ctx,
                                                                  ast.Store):
                            out.add(s2.id)
    return out


def local_names(node):
    """函数内定义的名字（参数、赋值、for、with、except、import、嵌套def）"""
    out = set()
    for a in list(node.args.args) + list(node.args.kwonlyargs):
        out.add(a.arg)
    if node.args.vararg:
        out.add(node.args.vararg.arg)
    if node.args.kwarg:
        out.add(node.args.kwarg.arg)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store,
                                                              ast.Del)):
            out.add(sub.id)
        elif isinstance(sub, ast.arg):
            out.add(sub.arg)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            out.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for a in sub.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)) and sub is not node:
            out.add(sub.name)
        elif isinstance(sub, ast.Global):
            out.update(sub.names)
    return out


def check_file(path):
    """★ 要正确处理【闭包】：
       嵌套函数可以读外层函数的局部变量、以及外层函数的参数。
       所以检查某个函数时，必须把【所有外层函数】的局部名也算进来。
       （第一版没做这个，于是 fn()/wrap()/loop() 这些闭包全成了误报，
         真正的 'sys' 未定义反而被淹没了 —— 这就是为什么我漏看了它。）
    """
    src = io.open(path, encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print("  ✗ %s 语法错误: %s" % (os.path.basename(path), e))
        return 1
    mods = module_names(tree)
    bad = []

    def walk_scope(node, outer):
        """node = 函数节点；outer = 外层所有可见名字的集合"""
        loc = local_names(node)
        visible = set(outer) | loc
        # 检查本函数【直接属于自己】的语句（不递归进嵌套函数体，
        # 嵌套函数会用自己的 visible 单独走一遍）
        for sub in node.body:
            for x in ast.walk(sub):
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and x is not node:
                    continue     # 嵌套函数的体会单独检查
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load):
                    n = x.id
                    if n in visible or n in mods or hasattr(builtins, n):
                        continue
                    bad.append((node.name, x.lineno, n))
            # 单独处理嵌套函数（带上当前可见集）
            for x in ast.walk(sub):
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and x is not node:
                    walk_scope(x, visible)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_scope(node, set())
    return bad


def main():
    files = sys.argv[1:] or DEFAULT
    total = 0
    print("=" * 70)
    print(" 未定义名字检查")
    print("=" * 70)
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(HERE, f)
        if not os.path.exists(p):
            continue
        bad = check_file(p)
        if isinstance(bad, int):
            total += bad
            continue
        uniq = sorted(set(bad))
        if uniq:
            print("  ✗ %s" % os.path.basename(p))
            seen = set()
            for fn, ln, n in uniq:
                key = (fn, n)
                if key in seen:
                    continue
                seen.add(key)
                print("       %s() 行 %d: 用了未定义的 %r" % (fn, ln, n))
            total += len(uniq)
        else:
            print("  ✓ %s" % os.path.basename(p))
    print()
    if total:
        print(" ★ 共 %d 处可疑（未定义名字会导致运行期 NameError）" % total)
    else:
        print(" 全部通过")
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main())
