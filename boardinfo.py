#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boardinfo.py —— 板子状态 + 跑一次卸载 A/B (run_perf.py auto) 做前后对比"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402
import deploy_gpu2026 as D         # noqa: E402


def root_run(script, timeout=1200, quiet=False, tag="s"):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    remote = "/tmp/_%s.sh" % tag
    board.put(local, remote)
    return board.run("echo %s | sudo -S -p '' bash %s" % (board.PASS, remote),
                     timeout=timeout, quiet=quiet)


INFO = r'''
echo "=== CPU ==="
for f in scaling_governor scaling_cur_freq scaling_max_freq; do
  printf '%-20s %s\n' "$f" "$(cat /sys/devices/system/cpu/cpu0/cpufreq/$f 2>/dev/null)"
done
grep -E "BogoMIPS|Features" /proc/cpuinfo | head -2
echo
echo "=== 内存 ==="; free -m | head -2
echo
echo "=== 服务 ==="
for s in zynq-desktop zynq-screen-guard wifi-connect ssh; do
  printf '%-20s %s\n' "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo
echo "=== 温度 / 频率 ==="; uptime
echo
echo "=== gpu_addr ==="; cat /home/zynq/.gpu_addr 2>/dev/null || echo "(none)"
'''


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "info"
    if what == "info":
        out, _ = root_run(INFO, tag="info")
        print(out)
    elif what == "perf":
        # 跑卸载 A/B: 需要把桌面停掉
        D.pause_guard(True)
        root_run("systemctl stop zynq-desktop zynq-screen-guard; sleep 1; "
                 "echo 0,0 > /sys/class/graphics/fb0/pan; pkill -9 -x python3 2>/dev/null; true",
                 timeout=120, tag="stopp")
        try:
            out, _ = root_run("cd /home/zynq/ui && python3 run_perf.py auto 2>&1; "
                              "echo RC=$?", timeout=1800, tag="perf")
            print(out)
            try:
                board.get("/tmp/gpuperf.txt", os.path.join(HERE, "res_perf_gpu64.txt"))
                print("  已存 res_perf_gpu64.txt")
            except Exception as e:
                print("  下载失败: %s" % e)
        finally:
            root_run("systemctl start zynq-desktop zynq-screen-guard; sleep 6; true",
                     timeout=180, tag="startp")
            D.pause_guard(False)


if __name__ == "__main__":
    main()
