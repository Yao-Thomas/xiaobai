#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""back_to_ours.py —— 重启验证 flag 自动退回 + 清理试用残留

现在板上: 他的内核 + 我们的 rootfs, /mnt/boot/use_ours.flag 已由 u-boot 写好。
重启后 u-boot 应该看到 flag -> 跳过他的分支 -> 走我们自己的 zImage/dt/bit。
这一步验证的就是"一次性"机制的另一半。
"""
import io
import socket
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
OUR_UTS = "#1 SMP PREEMPT Thu Sep 14 08:39:17 UTC 2023"


def port_open(t=2):
    try:
        s = socket.create_connection((IP, 22), timeout=t)
        s.close()
        return True
    except Exception:
        return False


def main():
    board.HOST = IP
    print("重启前: " + broot.srun("uname -v; ls -l /mnt/boot/use_ours.flag", quiet=True)[0].strip())

    try:
        broot.srun("sync; reboot", timeout=15, quiet=True)
    except Exception:
        pass

    t0 = time.time()
    while time.time() - t0 < 30:
        if not port_open():
            print("  %.0fs 掉线" % (time.time() - t0))
            break
        time.sleep(1)

    for _ in range(60):
        time.sleep(4)
        if port_open():
            break
    else:
        print("!! 没回来")
        return 1

    board.HOST = IP
    time.sleep(3)
    out, _ = broot.srun(
        "echo '### uname'; uname -v; echo '### ip'; ip -br addr show | grep wl; "
        "echo '### /proc/fb'; cat /proc/fb; echo '### lsmod'; lsmod; "
        "echo '### /mnt/boot'; ls -l /mnt/boot/use_ours.flag /mnt/boot/image.ub; "
        "echo '### failed'; systemctl --failed --no-pager", quiet=True)
    print(out)

    ok = OUR_UTS in out
    print(">>> 回到我们的系统: %s" % ("是" if ok else "否 !!!"))

    print("=" * 72)
    print("## 清理试用残留, 恢复正常态")
    broot.srun("rm -f /etc/his-trial-armed /home/zynq/.guard_pause; "
               "ls -l /etc/his-trial-armed /home/zynq/.guard_pause 2>&1; "
               "systemctl is-enabled his-trial-guard.service; "
               "systemctl start his-trial-guard.service 2>&1; "
               "systemctl status his-trial-guard.service --no-pager | head -6")

    print("=" * 72)
    print("## 我们的系统功能自检")
    broot.srun("cat /proc/fb; ls /dev/fb0; lsmod; "
               "systemctl is-active zynq-desktop zynq-screen-guard wifi-connect ssh; "
               "ls -l /dev/dri/ 2>&1")
    return 0


sys.exit(main())
