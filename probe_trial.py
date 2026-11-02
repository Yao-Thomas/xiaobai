#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_trial.py —— 试用前的环境确认"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board

CMDS = [
    "df -h /mnt/boot",
    "df -k /mnt/boot",
    "ls -l /mnt/boot/",
    "systemctl cat zynq-screen-guard.service",
    "ls -l /usr/local/bin/ /opt 2>/dev/null",
    "systemctl is-enabled zynq-screen-guard wifi-connect zynq-desktop",
]


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    for c in CMDS:
        print("=" * 70)
        print("$ " + c)
        out, err = board.run(c, timeout=30)
        print(out, end="")
        if err.strip():
            print("[stderr] " + err.strip())


main()
