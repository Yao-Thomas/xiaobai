#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell_lint.py —— 给 .sh 做个基础体检（PC 上没 bash 时用）

不能完全替代 `sh -n`，但能抓住最常见的致命错误：
    ① if / fi 不配对
    ② for / done 不配对
    ③ do / done 不配对
    ④ heredoc（<<EOF）不闭合
    ⑤ case / esac 不配对
    ⑥ CRLF 换行（Linux 上会报 "\r: command not found"）
    ⑦ 首行不是 #!/bin/sh 或 #!/bin/bash
    ⑧ 引号（单/双）总数是奇数

★ 为什么要做这个：PC 上没装 bash/WSL，而 .sh 的语法错
  只有在板子上跑才发现 —— 那时候已经浪费一次部署。
  （踩过：CRLF 导致音频修复那一步整个失败）

用法:
    python shell_lint.py                  # 检查当前目录所有 .sh
    python shell_lint.py deploy_all.sh
"""
import glob
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def strip_comments_and_heredocs(lines):
    """把注释行和 heredoc 内容剔掉，剩下的是真代码

    ★ 必须剔 heredoc：里面的 Python/JSON 会有 if、for 这些词，
      不剔掉就会误报。

    ★★★ 顺序有讲究（踩过两次）：
      必须在【剥引号之前】认 heredoc。因为常见写法是
          sudo python3 - <<'PY'
          ...
          PY
      strip_quoted 会把 'PY' 里的 PY 抹成空格，
      之后就匹配不到 heredoc 开始标记了 —— 于是 heredoc 里的
      Python `if` 全被当成 shell 的 if，报"if 少了 5 个 fi"这种假错。
      ⇒ 所以流程必须是：先剥 heredoc（在原文上）→ 再剥引号 → 再数关键字。
    """
    out = []
    heredoc_tag = None
    for ln in lines:
        s = ln.strip()
        if heredoc_tag is not None:
            if s == heredoc_tag:
                heredoc_tag = None
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", ln)
        if m:
            heredoc_tag = m.group(1)
            # heredoc 开始那行本身还是有代码的，保留
            out.append(ln[:m.start()])
            continue
        if s.startswith("#"):
            continue
        out.append(ln)
    return out


def strip_quoted(text):
    """把双引号/单引号字符串【里面的内容】换掉

    ★★★ 为什么必须做这一步（踩过）：
      脚本里常见这种写法：
          curl ... | python3 -c "
          ...
          if not d.get('ok'):
              ...
          "
      这些 `if` 是 **Python 的**，不是 shell 的。不剥掉的话
      会被数成 shell 的 if，于是报"if 少了 2 个 fi" —— 纯误报。
      （我第一版就这么误报了 install_cloud_api.sh）

    做法：用状态机扫一遍，字符串内部换成空格（保留长度和换行）。
    """
    out = []
    in_d = in_s = False
    esc = False
    for ch in text:
        if esc:
            out.append(" " if ch != "\n" else "\n")
            esc = False
            continue
        if ch == "\\":
            esc = True
            out.append(" ")
            continue
        if in_d:
            if ch == '"':
                in_d = False
                out.append('"')
            else:
                out.append(" " if ch != "\n" else "\n")
            continue
        if in_s:
            if ch == "'":
                in_s = False
                out.append("'")
            else:
                out.append(" " if ch != "\n" else "\n")
            continue
        if ch == '"':
            in_d = True
            out.append('"')
            continue
        if ch == "'":
            in_s = True
            out.append("'")
            continue
        out.append(ch)
    return "".join(out)


def check(path):
    raw = open(path, "rb").read()
    issues = []

    # ⑥ CRLF
    n_crlf = raw.count(b"\r\n")
    if n_crlf:
        issues.append("★ 有 %d 处 CRLF（Linux 上会报 $'\\r': command not found）"
                      % n_crlf)

    text = raw.decode("utf-8", "replace")
    lines = text.split("\n")

    # ⑦ shebang
    if lines and not lines[0].startswith("#!"):
        issues.append("首行不是 #!")

    # ★★★ 顺序：先在【原文】上剥 heredoc，再剥引号，最后数关键字。
    #   反过来的话 `<<'PY'` 里的 PY 会被 strip_quoted 抹掉，
    #   heredoc 就认不出来，里面的 Python 代码会被当成 shell —— 假错。
    after_heredoc = "\n".join(strip_comments_and_heredocs(lines))
    noq = strip_quoted(after_heredoc)
    code = noq.split("\n")

    # ① if/fi  (elif 和 else 不额外计数)
    d_if = 0
    for i, l in enumerate(code, 1):
        s = l.strip()
        if re.match(r"^if\s", s) or s == "if":
            d_if += 1
        elif re.match(r"^fi\b", s):
            d_if -= 1
            if d_if < 0:
                issues.append("第 %d 行 fi 多了一个" % i)
                break
    if d_if > 0:
        issues.append("if 少了 %d 个 fi" % d_if)

    # ② for / while / until -> do ... done
    d_do = 0
    for i, l in enumerate(code, 1):
        s = l.strip()
        if re.match(r"^(for|while|until)\s", s):
            d_do += 1
        elif re.match(r"^done\b", s):
            d_do -= 1
            if d_do < 0:
                issues.append("第 %d 行 done 多了一个" % i)
                break
    if d_do > 0:
        issues.append("有 %d 个 for/while 没配 done" % d_do)

    # ⑤ case/esac
    n_case = len([l for l in code if re.match(r"^case\s", l.strip())])
    n_esac = len([l for l in code if re.match(r"^esac\b", l.strip())])
    if n_case != n_esac:
        issues.append("case=%d esac=%d 不等" % (n_case, n_esac))

    # ④ heredoc 闭合（在原始文本上数）
    opens = re.findall(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text)
    for tag in set(opens):
        n_open = opens.count(tag)
        n_close = len(re.findall(r"^%s$" % re.escape(tag), text, re.M))
        if n_open != n_close:
            issues.append("heredoc <<%s 开了 %d 次、闭合 %d 次"
                          % (tag, n_open, n_close))

    # ⑧ 引号配平（粗略：只数没被转义的）
    for q, name in (('"', "双引号"), ("'", "单引号")):
        cnt = 0
        for l in code:
            # 去掉转义
            l2 = re.sub(r"\\.", "", l)
            cnt += l2.count(q)
        if cnt % 2:
            issues.append("%s 是奇数（%d 个）—— 可能没闭合" % (name, cnt))

    return issues


def main():
    args = sys.argv[1:]
    if not args:
        here = os.path.dirname(os.path.abspath(__file__))
        files = sorted(glob.glob(os.path.join(here, "*.sh")))
    else:
        files = args

    print("=" * 74)
    print(" shell 脚本体检（PC 上没 bash 时的替代）")
    print("=" * 74)

    bad = 0
    for f in files:
        if not os.path.exists(f):
            print("  ✗ 找不到 %s" % f)
            bad += 1
            continue
        iss = check(f)
        name = os.path.basename(f)
        if iss:
            bad += 1
            print("  ✗ %s" % name)
            for x in iss:
                print("      - %s" % x)
        else:
            print("  ✓ %s" % name)

    print()
    print("  %d 个文件，%d 个有问题" % (len(files), bad))
    print("  ★ 注意：这只做基础体检，真正的语法验证还是要 sh -n（在板子上）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
