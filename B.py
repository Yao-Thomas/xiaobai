#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B.py <本地脚本> [--user]  —— 上传脚本到板子并以 root (默认) 执行

用 shell 脚本文件而不是行内命令, 彻底绕开 PowerShell 的引号地狱。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board
import broot

if len(sys.argv) < 2:
    raise SystemExit(__doc__)

local = sys.argv[1]
as_user = "--user" in sys.argv
remote = "/tmp/_b_" + os.path.basename(local)

board.put(local, remote)
broot.srun("chmod +x %s; bash %s" % (remote, remote), use_sudo=not as_user)
