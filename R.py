#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""以 root 在板子上跑一段命令 (走 sudo)"""
import sys
sys.path.insert(0, r"D:\ubuntu_iso")
import broot

cmd = sys.argv[1] if len(sys.argv) > 1 else "id"
broot.srun(cmd)
