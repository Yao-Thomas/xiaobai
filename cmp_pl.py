#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmp_pl.py —— 我们的 PL 设计 vs 他的 PL 设计 (以真实枚举到的平台设备为准)

现在板子已经回到我们自己的系统 (我们的 system.bit)。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMDS = [
    ("A_our_pl_devices", "ls /sys/bus/platform/devices/ | sort"),
    ("B_our_amba_pl_dt", "for d in /proc/device-tree/amba_pl/*; do "
                         "echo \"== $(basename $d)  compat=$(tr '\\0' ' ' < $d/compatible 2>/dev/null)\"; "
                         "done"),
    ("C_our_drm", "for c in /sys/class/drm/card*/card*/status; do echo \"$c = $(cat $c)\"; done; "
                  "cat /proc/fb"),
    ("D_our_interrupts", "cat /proc/interrupts"),
    ("E_our_dmesg_pl", "dmesg | grep -iE 'xilinx|drm|fb0|xlnx|vtc|frmbuf|clk_wiz|audio|i2s|snd|"
                       "i2c|ov5640|vcap|dma|pwm|bridge|display|scope|gpu'"),
    ("F_our_iomem", "cat /proc/iomem"),
]


def main():
    board.HOST = IP
    res = {}
    for name, cmd in CMDS:
        out, _ = broot.srun(cmd, timeout=90, quiet=True)
        res[name] = out
        print("=" * 72)
        print("## " + name)
        print(out)

    # 设备名集合对比 (他的那份在 collect_trial 里存过)
    import os
    his_path = r"D:\ubuntu_iso\histrial\02_pl_devices.txt"
    if os.path.exists(his_path):
        his = set(open(his_path, encoding="utf8").read().split())
        our = set(res["A_our_pl_devices"].split())
        print("=" * 72)
        print("## 平台设备集合对比")
        print("  只有他有 (%d):" % len(his - our))
        for x in sorted(his - our):
            print("     " + x)
        print("  只有我们有 (%d):" % len(our - his))
        for x in sorted(our - his):
            print("     " + x)
        print("  两边都有 (%d)" % len(his & our))


main()
