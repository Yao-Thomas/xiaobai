#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_gputest.py —— 把「桌面默认不用 GPU + GPU 测试台」部署到板子并验证

步骤:
  1. 上传 desktop.py / apps_gpu.py / gputest_shot.py
  2. 确保 .gpu_desktop 标记【不存在】(桌面走软件渲染)
  3. 重启桌面, 截图 -> 应该看不到 GPU 徽章
  4. 停桌面, 独立跑一遍测试台逻辑, 截图
  5. 恢复桌面
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


def sh(cmd, timeout=300):
    return board.run(cmd, timeout=timeout)


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
    for f in ("desktop.py", "apps_gpu.py"):
        board.put(os.path.join(HERE, "ui", f), "/home/zynq/ui/%s" % f)
    board.put(os.path.join(HERE, "gputest_shot.py"), "/home/zynq/ui/gputest_shot.py")

    print("=== 2. 关掉桌面 GPU (删 .gpu_desktop, 保留 .gpu_addr) ===")
    root_run("rm -f /home/zynq/.gpu_desktop; "
             "echo -n '.gpu_addr   = '; cat /home/zynq/.gpu_addr; "
             "echo -n '.gpu_desktop= '; "
             "ls /home/zynq/.gpu_desktop 2>/dev/null || echo '(不存在 -> 桌面软件渲染)'",
             tag="flag")

    print("=== 3. 重启桌面 + 截图 ===")
    root_run("systemctl restart zynq-desktop; sleep 8; systemctl is-active zynq-desktop",
             timeout=180, tag="restart")
    time.sleep(3)
    shot("desktop_nogpu")
    print("   --- 桌面日志里的 GPU 行 ---")
    root_run("journalctl -u zynq-desktop -n 40 --no-pager | grep -i gpu | tail -5",
             timeout=60, tag="log")

    print("=== 4. 独立跑 GPU 测试台 ===")
    D.pause_guard(True)
    root_run("systemctl stop %s; sleep 1; echo 0,0 > /sys/class/graphics/fb0/pan; "
             "pkill -9 -x python3 2>/dev/null; true" % SVC, timeout=120, tag="stop")
    out, _ = root_run("cd /home/zynq/ui && timeout 25 python3 gputest_shot.py 20 2>&1",
                      timeout=300, tag="gputest")
    print(out)
    shot("gputest")
    print("=== 5. 恢复桌面 ===")
    root_run("systemctl start %s; sleep 6; true" % SVC, timeout=180, tag="start")
    D.pause_guard(False)
    sh("for s in %s; do printf '%%-20s %%s\\n' \"$s\" "
       "\"$(systemctl is-active $s)\"; done" % SVC)


if __name__ == "__main__":
    main()
