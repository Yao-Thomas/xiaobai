#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shotnow.py —— 用 sudo 抓一张板子屏幕截图并存到本地"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402


def root_run(script, timeout=180, tag="shot"):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    remote = "/tmp/_%s.sh" % tag
    board.put(local, remote)
    return board.run("echo %s | sudo -S -p '' bash %s" % (board.PASS, remote),
                     timeout=timeout)


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%m%d_%H%M%S")
    remote = "/home/zynq/shot_%s.png" % tag
    out, _ = root_run("cd /home/zynq/ui && python3 shot_board.py %s; echo RC=$?; "
                      "ls -l %s" % (remote, remote))
    print(out)
    local = os.path.join(HERE, "shot_%s.png" % tag)
    try:
        board.get(remote, local)
        print("已下载: %s  (%d 字节)" % (local, os.path.getsize(local)))
    except Exception as e:
        print("下载失败: %s" % e)


if __name__ == "__main__":
    main()
