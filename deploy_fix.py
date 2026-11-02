#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 A1/A2 的修复部署到板子

A1: ui/home.py     —— Wi-Fi 状态查询改到后台线程 (原来在 UI 线程上 os.popen("iw"),
                      驱动一卡整个桌面就冻住, 这就是"软件点不进去"的元凶)
A2: ui/desktop.py  —— 每秒写 /run/desktop_beat 心跳
    /usr/local/bin/desktop-watchdog.sh + .service + .timer
                    —— 心跳停 >25s 就 systemctl restart zynq-desktop
                       (zynq-screen-guard 只管黑屏, 管不了"画面冻住")
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board
import broot

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


FILES = [
    # (本地, 远端, 模式)
    (os.path.join(UI, "home.py"), "/home/zynq/ui/home.py", "0644"),
    (os.path.join(UI, "desktop.py"), "/home/zynq/ui/desktop.py", "0644"),
    (os.path.join(UI, "desktop-watchdog.sh"),
     "/usr/local/bin/desktop-watchdog.sh", "0755"),
    (os.path.join(UI, "desktop-watchdog.service"),
     "/etc/systemd/system/desktop-watchdog.service", "0644"),
    (os.path.join(UI, "desktop-watchdog.timer"),
     "/etc/systemd/system/desktop-watchdog.timer", "0644"),
]


def main():
    for local, remote, mode in FILES:
        tmp = "/tmp/_dep_" + os.path.basename(local)
        board.put(local, tmp)
        out, err = broot.srun(
            "install -o zynq -g zynq -m %s %s %s" % (mode, tmp, remote)
            if remote.startswith("/home/zynq")
            else "install -m %s %s %s" % (mode, tmp, remote), quiet=True)
        if err.strip() and "cannot" in err.lower():
            print("!! %s -> %s: %s" % (local, remote, err.strip()))
        print("   %s -> %s (%s)" % (os.path.basename(local), remote, mode))

    print("\n--- md5 核对")
    for local, remote, _ in FILES:
        out, _ = broot.srun("md5sum %s" % remote, quiet=True)
        got = out.split()[0] if out.strip() else "?"
        want = md5(local)
        print("   %-46s %s %s" % (remote, got, "OK" if got == want else
                                  "!! 期望 " + want))

    print("\n--- 启用看门狗")
    broot.srun("systemctl daemon-reload && "
               "systemctl enable --now desktop-watchdog.timer", quiet=False)
    broot.srun("systemctl list-timers desktop-watchdog.timer --no-pager")


if __name__ == "__main__":
    print("HOST =", board.HOST)
    main()
