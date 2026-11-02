#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guard.py —— 危险操作防护

对应 DeepSeek Harness 的 `dsh-sandbox-policy` / `dsh-user-approval` /
`dsh-permission-presets`。

和 Harness 的差别：那边有真人点"批准"；这台设备大多数时候**没人在旁边**，
所以策略是 **"默认拒绝 + 把原因告诉模型"** ——
模型会自己换个安全的做法，而不是硬闯。
"""
import re

from . import config


class Verdict(object):
    def __init__(self, allow, level, why=""):
        self.allow = allow
        self.level = level      # ok / confirm / deny
        self.why = why

    def __repr__(self):
        return "Verdict(%s,%s,%s)" % (self.allow, self.level, self.why)


def check(cmd, cfg=None, approved=False):
    """检查一条 shell 命令。

    level: ok       直接跑
           confirm  需要确认（有真人时问，没人时拒绝）
           deny     一律拒绝
    """
    cfg = cfg or config.load()
    c = (cmd or "").strip()
    if not c:
        return Verdict(False, "deny", "空命令")

    for p in cfg["deny_patterns"]:
        if re.search(p, c, re.I):
            return Verdict(False, "deny",
                           "命中禁止规则 /%s/（这条命令可能让设备变砖或丢数据）" % p)

    for p in cfg["confirm_patterns"]:
        if re.search(p, c, re.I):
            if approved:
                return Verdict(True, "confirm", "已确认")
            return Verdict(False, "confirm",
                           "这条命令可能改东西（命中 /%s/），需要确认" % p)

    return Verdict(True, "ok", "")


def check_path(path, cfg=None, write=False):
    """限制文件操作在 workdir 内（除非明确允许）"""
    import os
    cfg = cfg or config.load()
    try:
        p = os.path.abspath(os.path.expanduser(path))
    except Exception:
        return Verdict(False, "deny", "路径无法解析")
    wd = os.path.abspath(cfg["workdir"])
    if not p.startswith(wd):
        # 读系统文件是允许的（agent 需要看 /proc /sys）
        if write:
            return Verdict(False, "deny",
                           "只允许写 %s 下面的文件（要写别处请让用户改 workdir）" % wd)
        return Verdict(True, "ok", "系统路径只读")
    return Verdict(True, "ok", "")
