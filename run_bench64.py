#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_bench64.py —— 64 位 GPU 一键: 装比特流 -> 重启 -> 探测 -> 真机基准 -> 截图

用法:
    python run_bench64.py install   只装比特流 + 重启
    python run_bench64.py bench     只跑基准 (板子已经在跑新比特流)
    python run_bench64.py auto      全套
    python run_bench64.py revert    退回旧比特流
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

BENCH_LOCAL = os.path.join(HERE, "ui", "bench_gpu64.py")
BENCH_REMOTE = "/home/zynq/ui/bench_gpu64.py"
RESULT_REMOTE = "/tmp/gpu64.txt"

STOP_SVC = "zynq-desktop zynq-screen-guard"
SVC = "zynq-desktop zynq-screen-guard wifi-connect ssh"


def sh(cmd, timeout=300, quiet=False):
    return board.run(cmd, timeout=timeout, quiet=quiet)


def root_run(script, timeout=900, quiet=False, tag="step"):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    remote = "/tmp/_%s.sh" % tag
    board.put(local, remote)
    cmd = "echo %s | sudo -S -p '' bash %s" % (board.PASS, remote)
    return board.run(cmd, timeout=timeout, quiet=quiet)


def stop_desktop():
    D.pause_guard(True)
    print("  停桌面 + 看门狗 ...")
    root_run("systemctl stop %s; sleep 1; "
             "echo 0,0 > /sys/class/graphics/fb0/pan; "
             "pkill -9 -x python3 2>/dev/null; "
             "for s in %s; do printf '%%-20s %%s\\n' \"$s\" "
             "\"$(systemctl is-active $s 2>/dev/null)\"; done"
             % (STOP_SVC, SVC), timeout=120, tag="stop")


def start_desktop():
    root_run("systemctl start %s; sleep 6" % STOP_SVC, timeout=180, tag="start")
    D.pause_guard(False)


def run_bench(mode):
    """mode: gpu / cpu / both"""
    print("  上传 bench_gpu64.py ...")
    board.put(BENCH_LOCAL, BENCH_REMOTE)
    print("  跑基准 (要几十秒) ...")
    out, _ = root_run("cd /home/zynq/ui && python3 bench_gpu64.py 2>&1; "
                      "echo RC=$?", timeout=1800, tag="bench")
    print(out)
    try:
        local = os.path.join(HERE, "res_bench_gpu64.txt")
        board.get(RESULT_REMOTE, local)
        print("  结果已存: %s" % local)
    except Exception as e:
        print("  下载 /tmp/gpu64.txt 失败: %s" % e)
    return out


def grab_shot(tag):
    remote = "/home/zynq/shot_%s.png" % tag
    root_run("cd /home/zynq/ui && python3 shot_board.py %s; echo RC=$?" % remote,
             timeout=180, quiet=True, tag="shot")
    local = os.path.join(HERE, "shot_%s.png" % tag)
    try:
        board.get(remote, local)
        print("  截图: %s" % local)
        return local
    except Exception as e:
        print("  截图失败: %s" % e)
        return None


def cmd_install():
    D.pause_guard(True)
    D.install("fullbit")
    D.cmd_reboot()
    D.pause_guard(False)


def cmd_verify():
    if not board.HOST and not D.wait_ssh(120):
        return False
    sh("uptime")
    gpu_ok, lcd_ok, note = D.verify_once("gpu64")
    print("  GPU 探测: %s" % ("OK" if gpu_ok else "失败"))
    return gpu_ok


def cmd_bench(with_shot=True):
    if not board.HOST and not D.wait_ssh(120):
        return
    stop_desktop()
    try:
        run_bench("both")
    finally:
        if with_shot:
            grab_shot("gpu64_bench")
    print("\n  恢复桌面 ...")
    start_desktop()
    print("  服务: ")
    sh(D.svc_state())


def cmd_auto():
    cmd_install()
    if not cmd_verify():
        print("!! GPU 没起来, 先别跑基准")
        return
    cmd_bench()


DISPATCH = {
    "install": cmd_install,
    "verify": cmd_verify,
    "bench": cmd_bench,
    "auto": cmd_auto,
    "revert": D.cmd_revert,
    "status": D.cmd_status,
}

if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if a in DISPATCH:
        DISPATCH[a]()
    else:
        print(__doc__)
