#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reboot_wait.py —— 重启板子并等它回来"""
import io
import socket
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board

IP = "192.168.10.18"


def port_open(ip, t=2):
    try:
        s = socket.create_connection((ip, 22), timeout=t)
        s.close()
        return True
    except Exception:
        return False


def main():
    print("重启前: 22 端口 %s" % ("开" if port_open(IP) else "不通"))
    try:
        board.HOST = IP
        board.run("sudo -n reboot 2>&1 || sudo -n shutdown -r now 2>&1", timeout=15, quiet=True)
    except Exception as e:
        print("(reboot 命令返回异常, 正常: %s)" % e)

    print("已发重启, 等它掉线 ...")
    t0 = time.time()
    while time.time() - t0 < 25:
        if not port_open(IP):
            print("  %.1fs 掉线" % (time.time() - t0))
            break
        time.sleep(1)

    print("等它回来 (最多 240s) ...")
    t0 = time.time()
    while time.time() - t0 < 240:
        if port_open(IP):
            try:
                c = board.conn()
                c.close()
                print("  %.1fs 端口开且能登录" % (time.time() - t0))
                break
            except Exception:
                pass
        time.sleep(3)
    else:
        print("!! 240s 没回来")
        return 1

    board.HOST = IP
    out, _ = board.run("uptime; uname -v; cat /proc/cmdline; md5sum /mnt/boot/boot.scr; "
                       "ls -l /mnt/boot/use_ours.flag /mnt/boot/image.ub 2>&1; "
                       "systemctl --failed --no-pager; "
                       "ip -br addr show | grep wl", timeout=60)
    print(out)
    return 0


sys.exit(main())
