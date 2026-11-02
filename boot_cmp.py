#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boot_cmp.py —— 对比「别人的 boot.zip」和板子现有启动分区"""
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
echo "=== /mnt/boot 内容 ==="
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -l /mnt/boot/ 2>/dev/null
echo
echo "=== 各文件 md5 (前 8 位) ==="
for f in /mnt/boot/BOOT.BIN /mnt/boot/image.ub /mnt/boot/boot.scr; do
    [ -f "$f" ] && md5sum "$f"
done
echo
echo "=== 内核版本 ==="
uname -a
cat /proc/device-tree/model 2>/dev/null; echo
echo
echo "=== 现有 DTB 里的 model / compatible ==="
if [ -f /sys/firmware/devicetree/base/model ]; then
    tr -d '\0' < /sys/firmware/devicetree/base/model; echo
fi
umount /mnt/boot 2>/dev/null
'''


def main():
    local = os.path.join(HERE, "_tmp_bootcmp.sh")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + SCRIPT)
    board.put(local, "/tmp/_bootcmp.sh")
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_bootcmp.sh" % board.PASS,
                       timeout=120)
    print(out)


if __name__ == "__main__":
    main()
