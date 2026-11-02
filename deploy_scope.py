#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_scope.py —— 部署示波器并验证

步骤:
  1. 上传 scope.c / scope.py / apps_scope.py / desktop.py / scopetest_shot.py
  2. 在板子上编 libscope.so
  3. 写 .scope_addr 标记
  4. 独立跑一遍示波器, 截图
  5. 重启桌面 (多了"示波器"图标), 截图
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
SCOPE_BASE = 0x43CC0000


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
        return local
    except Exception as e:
        print("   截图失败: %s" % e)
        return None


def main():
    print("=== 1. 上传 ===")
    for f in ("scope.c", "scope.py", "apps_scope.py"):
        board.put(os.path.join(HERE, "ui", f), "/home/zynq/ui/%s" % f)
    board.put(os.path.join(HERE, "ui", "desktop.py"), "/home/zynq/ui/desktop.py")
    board.put(os.path.join(HERE, "scopetest_shot.py"),
              "/home/zynq/ui/scopetest_shot.py")

    print("=== 2. 编 libscope.so ===")
    out, _ = root_run("cd /home/zynq/ui && gcc -O2 -shared -fPIC -o libscope.so "
                      "scope.c 2>&1; echo RC=$?; ls -l libscope.so", tag="build")
    print(out)

    print("=== 3. 写 .scope_addr ===")
    out, _ = root_run("echo 0x%08X > /home/zynq/.scope_addr; "
                      "chown zynq:zynq /home/zynq/.scope_addr; "
                      "cat /home/zynq/.scope_addr" % SCOPE_BASE, tag="flag")
    print(out)

    print("=== 4. 独立跑示波器 ===")
    D.pause_guard(True)
    root_run("systemctl stop %s; sleep 1; echo 0,0 > /sys/class/graphics/fb0/pan; "
             "pkill -9 -x python3 2>/dev/null; true" % SVC, timeout=120, tag="stop")
    out, _ = root_run("cd /home/zynq/ui && timeout 40 python3 scopetest_shot.py 25 2>&1",
                      timeout=300, tag="scopetest")
    print(out)
    shot("scope")

    print("=== 5. 重启桌面 ===")
    root_run("systemctl start %s; sleep 8; true" % SVC, timeout=180, tag="start")
    D.pause_guard(False)
    time.sleep(2)
    shot("desktop_scope")


if __name__ == "__main__":
    main()
