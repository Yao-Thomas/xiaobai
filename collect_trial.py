#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_trial.py —— 趁着板子跑在他的系统上, 把现场全抓下来"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

BOARD = "/tmp/histrial"
LOCAL = r"D:\ubuntu_iso\histrial"
IP = "192.168.10.18"

CMDS = [
    ("01_uname", "uname -a; echo; cat /proc/cmdline; echo; cat /proc/version"),
    ("02_pl_devices", "ls /sys/bus/platform/devices/ | sort"),
    ("03_amba_pl_dt", "for d in /proc/device-tree/amba_pl/*; do "
                      "echo \"== $(basename $d)  compat=$(tr '\\0' ' ' < $d/compatible 2>/dev/null)\"; "
                      "done"),
    ("04_drm", "ls -l /dev/dri/; echo '--- card0 ---'; cat /sys/class/drm/card0/device/uevent 2>&1; "
               "echo '--- card1 ---'; cat /sys/class/drm/card1/device/uevent 2>&1; "
               "echo '--- connectors ---'; for c in /sys/class/drm/card*/card*/status; do "
               "echo \"$c = $(cat $c)\"; done"),
    ("05_fb", "cat /proc/fb; echo '---'; for f in name virtual_size bits_per_pixel stride smem_len; do "
              "echo -n \"$f=\"; cat /sys/class/graphics/fb0/$f 2>&1; done"),
    ("06_modules", "lsmod"),
    ("07_dmesg_full", "dmesg"),
    ("08_dmesg_pl", "dmesg | grep -iE 'xilinx|drm|fb0|xlnx|v-tc|vtc|frmbuf|clk_wiz|audio|i2s|snd|"
                    "i2c|ov5640|vcap|dma|gpio|pwm|bridge|display'"),
    ("09_interrupts", "cat /proc/interrupts"),
    ("10_iomem", "cat /proc/iomem"),
    ("11_services", "systemctl --failed --no-pager; echo '--- running ---'; "
                    "systemctl list-units --type=service --state=running --no-pager"),
    ("12_desktop_log", "journalctl -u zynq-desktop --no-pager -n 60 2>&1; "
                       "echo '=== guard log ==='; tail -40 /var/log/zynq-screen-guard.log 2>&1"),
    ("13_i2c", "ls /dev/i2c-*; echo '--- i2cdetect 没有就算了 ---'; which i2cdetect"),
    ("14_video", "ls /dev/video* /dev/media* 2>&1; echo '--- v4l ---'; "
                 "for v in /sys/class/video4linux/*; do echo \"$v = $(cat $v/name 2>/dev/null)\"; done"),
    ("15_trial_report", "ls -l /root/his_trial/; echo '=========='; "
                        "cat /root/his_trial/report_*.txt"),
    ("16_flags", "ls -l /mnt/boot/use_ours.flag /etc/his-trial-armed /home/zynq/.guard_pause 2>&1; "
                 "echo '--- /mnt/boot ---'; ls -l /mnt/boot/"),
]


def main():
    board.HOST = IP
    os.makedirs(LOCAL, exist_ok=True)
    broot.srun("mkdir -p " + BOARD + "; chmod 777 " + BOARD)

    for name, cmd in CMDS:
        print("=" * 72)
        print("## " + name)
        out, _ = broot.srun(cmd, timeout=120, quiet=True)
        path = os.path.join(LOCAL, name + ".txt")
        with open(path, "w", encoding="utf8") as f:
            f.write(out)
        print("   -> %s (%d 字节)" % (path, len(out)))
        if name in ("01_uname", "06_modules", "05_fb", "11_services"):
            print(out)

    # 抓屏幕
    print("=" * 72)
    print("## 抓屏幕")
    broot.srun("dd if=/dev/fb0 of=/tmp/histrial/fb0.raw bs=1M count=2 2>&1; "
               "ls -l /tmp/histrial/fb0.raw", timeout=60)
    try:
        board.get("/tmp/histrial/fb0.raw", os.path.join(LOCAL, "fb0.raw"))
        print("已下载 fb0.raw")
    except Exception as e:
        print("下载 fb0 失败: %s" % e)


main()
