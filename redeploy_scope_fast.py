#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redeploy_scope_fast.py —— 只更新 PS 侧 (C + py) 并复测帧率, 不重启、不重出流"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

SVC = "zynq-desktop zynq-screen-guard"


def rr(script, tag, timeout=400):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    board.put(local, "/tmp/_%s.sh" % tag)
    return board.run("echo %s | sudo -S -p '' bash /tmp/_%s.sh" % (board.PASS, tag),
                     timeout=timeout)


def shot(tag):
    remote = "/home/zynq/shot_%s.png" % tag
    rr("cd /home/zynq/ui && python3 shot_board.py %s >/dev/null 2>&1; ls -l %s"
       % (remote, remote), "sh", 180)
    local = os.path.join(HERE, "shot_%s.png" % tag)
    try:
        board.get(remote, local)
        print("   截图: %s" % local)
    except Exception as e:
        print("   截图失败: %s" % e)


def main():
    print("=== 上传 ===")
    for f in ("scope.c", "scope.py", "apps_scope.py"):
        board.put(os.path.join(HERE, "ui", f), "/home/zynq/ui/%s" % f)
    board.put(os.path.join(HERE, "scopetiming_shot.py"),
              "/home/zynq/ui/scopetiming_shot.py")

    print("=== 重编 libscope.so ===")
    out, _ = rr("cd /home/zynq/ui && gcc -O2 -shared -fPIC -o libscope.so "
                "scope.c 2>&1; echo RC=$?; ls -l libscope.so", "build")
    print(out)

    print("=== 停桌面 -> 复测 ===")
    rr("systemctl stop %s; sleep 1; echo 0,0 > /sys/class/graphics/fb0/pan; "
       "pkill -9 -x python3 2>/dev/null; true" % SVC, "stop", 120)
    out, _ = rr("cd /home/zynq/ui && timeout 90 python3 scopetiming_shot.py 12 2>&1",
                "tim", 400)
    print(out)
    shot("scope_fast")

    print("=== 恢复桌面 ===")
    rr("systemctl start %s; sleep 6; true" % SVC, "go", 200)
    shot("desktop_scope_fast")


if __name__ == "__main__":
    main()
