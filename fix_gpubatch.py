#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_gpubatch.py —— 在板子上重新编译 libgpubatch.so 并重跑 GPU 测试台

修的 bug: gb_batch / cb_rects 里把【矩形】的规范化检查
          `if (x1<x0 || y1<y0) continue;` 套用到了【直线】上,
          导致向左/向上的线被静默丢弃。
"""
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
import deploy_gpu2026 as D         # noqa: E402

SVC = "zynq-desktop zynq-screen-guard"


def root_run(script, timeout=600, tag="s"):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    remote = "/tmp/_%s.sh" % tag
    board.put(local, remote)
    return board.run("echo %s | sudo -S -p '' bash %s" % (board.PASS, remote),
                     timeout=timeout)


def shot(tag):
    remote = "/home/zynq/shot_%s.png" % tag
    root_run("cd /home/zynq/ui && python3 shot_board.py %s >/dev/null 2>&1; "
             "ls -l %s" % (remote, remote), timeout=180, tag="sh")
    local = os.path.join(HERE, "shot_%s.png" % tag)
    try:
        board.get(remote, local)
        print("   截图: %s" % local)
    except Exception as e:
        print("   截图失败: %s" % e)


def main():
    print("=== 上传 gpubatch.c / apps_gpu.py ===")
    board.put(os.path.join(HERE, "gpubatch.c"), "/home/zynq/ui/gpubatch.c")
    board.put(os.path.join(HERE, "ui", "apps_gpu.py"), "/home/zynq/ui/apps_gpu.py")

    print("=== 重新编译 libgpubatch.so ===")
    out, _ = root_run("cd /home/zynq/ui && cp -f libgpubatch.so "
                      "libgpubatch.so.bak_shadowbug 2>/dev/null; "
                      "gcc -O2 -shared -fPIC -o libgpubatch.so gpubatch.c -lm 2>&1; "
                      "echo RC=$?; ls -l libgpubatch.so", tag="build")
    print(out)

    print("=== 停桌面, 重跑测试台 ===")
    D.pause_guard(True)
    root_run("systemctl stop %s; sleep 1; echo 0,0 > /sys/class/graphics/fb0/pan; "
             "pkill -9 -x python3 2>/dev/null; true" % SVC, timeout=120, tag="stop")
    out, _ = root_run("cd /home/zynq/ui && timeout 25 python3 gputest_shot.py 20 2>&1",
                      timeout=300, tag="gputest")
    print(out)
    shot("gputest2")

    print("=== 恢复桌面 ===")
    root_run("systemctl start %s; sleep 6; true" % SVC, timeout=180, tag="start")
    D.pause_guard(False)


if __name__ == "__main__":
    main()
