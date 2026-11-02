#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolcheck.py —— 查板子上有哪些做 FIT / 设备树 / 内核模块的工具"""
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
echo "=== 1. 关键工具 ==="
for t in mkimage dtc fdtput fdtget fdtdump gcc make modprobe insmod depmod; do
    printf '  %-10s %s\n' "$t" "$(command -v $t 2>/dev/null || echo '(无)')"
done

echo
echo "=== 2. 内核模块目录 ==="
ls -l /lib/modules/
echo "--- extra ---"
ls -l /lib/modules/$(uname -r)/extra/ 2>/dev/null
echo "--- 有没有 build / source (编译模块要用) ---"
ls -ld /lib/modules/$(uname -r)/build /lib/modules/$(uname -r)/source 2>/dev/null \
    || echo "  (没有 build/source —— 没法在这里重新编译模块)"

echo
echo "=== 3. WiFi 固件与配置 ==="
ls /lib/firmware/ | head -20
echo "--- aic8800D80 ---"
ls -l /lib/firmware/aic8800D80/ 2>/dev/null | head
echo "--- wifi 相关服务/配置 ---"
ls -l /etc/systemd/system/ | grep -i -E "wifi|wpa|net" 
ls -l /etc/wpa_supplicant* /etc/network/interfaces* 2>/dev/null
systemctl is-enabled wifi-connect 2>/dev/null
echo "--- wifi-connect 服务内容 ---"
systemctl cat wifi-connect 2>/dev/null | head -25

echo
echo "=== 4. 模块的 vermagic / CRC 关键符号 ==="
modinfo -F vermagic /lib/modules/$(uname -r)/extra/aic8800_fdrv.ko
echo "--- 模块依赖的内核符号 (前 15 个) ---"
modprobe --show-depends aic8800_fdrv 2>&1 | head -6
nm -u /lib/modules/$(uname -r)/extra/aic8800_fdrv.ko 2>/dev/null | head -12 \
    || echo "  (没有 nm)"

echo
echo "=== 5. 启动分区现状 ==="
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -l /mnt/boot/ | grep -v -E "System Volume"
df -h /mnt/boot
umount /mnt/boot 2>/dev/null
'''


def main():
    board.HOST = board.find_host(verbose=False)
    if not board.HOST:
        raise SystemExit("板子不在线")
    local = os.path.join(HERE, "_tmp_toolcheck.sh")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + SCRIPT)
    board.put(local, "/tmp/_toolcheck.sh")
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_toolcheck.sh" % board.PASS,
                       timeout=180)
    print(out)


if __name__ == "__main__":
    main()
