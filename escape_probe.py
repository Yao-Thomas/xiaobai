#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""escape_probe.py —— 在动他的系统之前, 先确认"退路"存在

退路候选:
  1. 有线网口 (eth0) 插了线且能起来 -> 最强退路
  2. 他的内核里有没有别的 WiFi 驱动
  3. 我们的模块 vermagic 和 modversions 情况
"""
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
echo "=========== 1. 有线网口 ==========="
for i in $(ls /sys/class/net); do
    printf '%-10s ' "$i"
    if [ -e /sys/class/net/$i/carrier ]; then
        printf 'carrier=%s ' "$(cat /sys/class/net/$i/carrier 2>/dev/null)"
    fi
    printf 'operstate=%s ' "$(cat /sys/class/net/$i/operstate 2>/dev/null)"
    printf 'mac=%s\n' "$(cat /sys/class/net/$i/address 2>/dev/null)"
done
echo
echo "--- ip 地址 ---"
ip -4 addr show | grep -E "^[0-9]+:|inet "
echo
echo "--- eth0 详细信息 ---"
if [ -d /sys/class/net/eth0 ]; then
    echo "  speed=$(cat /sys/class/net/eth0/speed 2>/dev/null)"
    echo "  duplex=$(cat /sys/class/net/eth0/duplex 2>/dev/null)"
    echo "  carrier_changes=$(cat /sys/class/net/eth0/carrier_changes 2>/dev/null)"
fi
echo
echo "=========== 2. WiFi 是什么总线 ==========="
lsusb 2>/dev/null | head -10 || echo "(没有 lsusb)"
echo "--- USB 设备 ---"
for d in /sys/bus/usb/devices/*/; do
    [ -f "$d/idVendor" ] && echo "  $d  $(cat $d/idVendor):$(cat $d/idProduct)  $(cat $d/product 2>/dev/null)"
done
echo
echo "=========== 3. 我们的 WiFi 模块 ==========="
MOD=/lib/modules/$(uname -r)/extra/aic8800_fdrv.ko
for m in /lib/modules/$(uname -r)/extra/*.ko /lib/modules/$(uname -r)/updates/*.ko; do
    [ -f "$m" ] && echo "  模块: $m"
done
modinfo aic8800_fdrv 2>/dev/null | grep -E "vermagic|filename" 
echo "--- 已加载 ---"
lsmod | head -15
echo
echo "=========== 4. SD 卡布局 ==========="
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT | grep -E "NAME|mmcblk"
echo
echo "=========== 5. 启动分区内容 ==========="
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -l /mnt/boot/
echo
echo "--- 我们现在的 boot.scr 里有没有 image.ub 分支 ---"
if [ -f /mnt/boot/boot.scr ]; then
    strings /mnt/boot/boot.scr | grep -n -E "image\.ub|zImage|system.*bit|fpga|devtype" | head -20
else
    echo "(没有 boot.scr!)"
fi
umount /mnt/boot 2>/dev/null
'''


def main():
    board.HOST = board.find_host(verbose=False)
    if not board.HOST:
        raise SystemExit("板子不在线")
    local = os.path.join(HERE, "_tmp_escape.sh")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + SCRIPT)
    board.put(local, "/tmp/_escape.sh")
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_escape.sh" % board.PASS,
                       timeout=180)
    print(out)


if __name__ == "__main__":
    main()
