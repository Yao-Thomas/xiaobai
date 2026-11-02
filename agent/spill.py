#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spill.py —— 输出治理：长输出落盘 + 只回摘要 + token 估算

★ 这是整个 Agent 里**最重要**的一块（对应 DeepSeek Harness 的
  `dsh-output-retention` / `dsh-spill` / `dsh-spill-policy` / `dsh-token-meter`）。

为什么重要：
  模型能不能干好活，很大程度取决于"**喂给它的工具结果是不是够用又不过量**"。
  - 全量灌进去 → 上下文爆炸、关键信息被淹没、很快就要压缩
  - 砍得太狠   → 模型看不到关键行，开始瞎猜

Harness 的做法（我照抄）：
  超过阈值的结果**原样写到磁盘**，回给模型的是
  「头部 N 行 + ……省略 X 行…… + 尾部 M 行 + 完整文件路径」。
  模型需要细节时可以再用 read/grep 去看那个文件 —— **信息没丢，只是不在上下文里**。
"""
import os
import re
import time

from . import config


def _human(n):
    for u in ("B", "K", "M"):
        if n < 1024:
            return "%d%s" % (n, u)
        n //= 1024
    return "%dG" % n


def est_tokens(text):
    """粗估 token 数。

    中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。
    不用精确 —— 只用来判断"该不该压缩"。
    """
    if not text:
        return 0
    n = len(text)
    cjk = len(re.findall(r"[\u2e80-\u9fff\uff00-\uffef\u3000-\u303f]", text))
    return int(cjk + (n - cjk) / 3.5)


def spill(name, text, cfg=None):
    """把长文本原样落盘，返回文件路径"""
    cfg = cfg or config.load()
    safe = re.sub(r"[^\w.-]+", "_", name)[:40]
    p = os.path.join(cfg["spill_dir"], "%s_%s.txt"
                     % (time.strftime("%m%d_%H%M%S"), safe))
    try:
        with open(p, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
    except Exception as e:
        return None, str(e)
    return p, None


def govern(name, text, cfg=None, force_spill=False):
    """工具结果的统一出口：需要时就落盘 + 摘要。

    返回 (给模型看的字符串, 是否落盘)
    """
    cfg = cfg or config.load()
    if text is None:
        return "(无输出)", False
    text = str(text)
    lines = text.split("\n")
    over = (len(text) > cfg["inline_chars"] or len(lines) > cfg["inline_lines"])

    if not over and not force_spill:
        return text, False

    path, err = spill(name, text, cfg)
    if err or not path:
        # 落盘失败就退化为"硬截断"，至少别把上下文撑爆
        head = "\n".join(lines[:cfg["head_lines"]])
        return (head + "\n\n…（输出 %d 行 / %s，落盘失败：%s）"
                % (len(lines), _human(len(text)), err)), False

    h = cfg["head_lines"]
    t = cfg["tail_lines"]
    if len(lines) <= h + t:
        body = text
    else:
        body = ("\n".join(lines[:h])
                + "\n\n…… 省略 %d 行 ……\n\n" % (len(lines) - h - t)
                + "\n".join(lines[-t:]))
    return ("%s\n\n[完整输出 %d 行 / %s 已存到 %s —— 需要细节用 read/grep 看它]"
            % (body, len(lines), _human(len(text)), path)), True


def context_chars(messages):
    """估算整段对话的字符数（压缩判断用）"""
    n = 0
    for m in messages:
        n += len(str(m.get("content") or ""))
        for tc in (m.get("tool_calls") or []):
            n += len(str(tc))
    return n
