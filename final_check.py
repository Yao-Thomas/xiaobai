#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_check.py —— 板子最终状态检查"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

SCRIPT = r'''
echo "=== 标记文件 ==="
printf '%-14s ' ".gpu_addr";    cat /home/zynq/.gpu_addr 2>/dev/null || echo "(无)"
printf '%-14s ' ".gpu_desktop"; ls /home/zynq/.gpu_desktop >/dev/null 2>&1 \
    && echo "存在 -> 桌面会使用 GPU" || echo "不存在 -> 桌面软件渲染 (期望)"
echo
echo "=== 服务 ==="
for s in zynq-desktop zynq-screen-guard wifi-connect ssh; do
    printf '%-20s %s\n' "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo
echo "=== GPU 探测 ==="
cd /home/zynq/ui && python3 gpu_probe.py 2>&1 | head -5
echo
echo "=== 关键文件 ==="
ls -l /home/zynq/ui/libgpubatch.so /home/zynq/ui/apps_gpu.py \
      /home/zynq/ui/desktop.py /home/zynq/ui/gputest_shot.py 2>&1
echo
echo "=== 桌面日志里 GPU 相关行 (应该说不使用 GPU) ==="
journalctl -u zynq-desktop -n 60 --no-pager 2>/dev/null | grep -i "gpu" | tail -4
echo
echo "=== pan ==="; cat /sys/class/graphics/fb0/pan
echo "=== uptime ==="; uptime
'''


def main():
    local = os.path.join(HERE, "_tmp_final.sh")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + SCRIPT)
    board.put(local, "/tmp/_final.sh")
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_final.sh" % board.PASS,
                       timeout=120)
    print(out)


if __name__ == "__main__":
    main()
