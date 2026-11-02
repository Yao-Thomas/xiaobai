#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_http.py —— 板子能不能从 PC 的 HTTP 服务拉文件"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board

CMDS = [
    "ping -c 2 -W 2 192.168.10.17",
    "which wget; wget --help 2>&1 | head -20",
    "cd /tmp && rm -f t.scr && wget -T 10 -O t.scr http://192.168.10.17:8899/boot.scr 2>&1 | tail -5; ls -l /tmp/t.scr; md5sum /tmp/t.scr",
]


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    for c in CMDS:
        print("=" * 70)
        print("$ " + c)
        out, err = board.run(c, timeout=60)
        print(out, end="")
        if err.strip():
            print("[stderr] " + err.strip())


main()
