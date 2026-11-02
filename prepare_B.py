#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prepare_B.py —— 阶段 B 前置: 挂 boot 分区 + 把自愈服务的触发条件挪到 rootfs 上

发现: /etc/fstab 只有根分区, /mnt/boot 开机不会自动挂载, 之前是手工挂的。
      这会让 his-trial-guard.service 的 ConditionPathExists=/mnt/boot/image.ub 失效。
两处修:
  1. fstab 加 /dev/mmcblk0p1 -> /mnt/boot  (nofail, 挂不上也不会进 emergency)
  2. unit 的条件改成 rootfs 上的标记文件 /etc/his-trial-armed (不依赖 FAT 挂载)
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)

    print("=" * 72)
    print("## 当前 fstab")
    broot.srun("cat /etc/fstab")

    print("=" * 72)
    print("## 写 fstab (备份原文件)")
    broot.srun(
        "set -e; "
        "[ -f /etc/fstab.orig_before_histrial ] || cp -a /etc/fstab /etc/fstab.orig_before_histrial; "
        "grep -q '/mnt/boot' /etc/fstab || "
        "  printf '/dev/mmcblk0p1\\t/mnt/boot\\tvfat\\tdefaults,noatime,nofail\\t0\\t0\\n' >> /etc/fstab; "
        "cat /etc/fstab"
    )

    print("=" * 72)
    print("## unit 换成 rootfs 标记文件")
    broot.srun(
        "set -e; "
        "sed -i 's#^ConditionPathExists=.*#ConditionPathExists=/etc/his-trial-armed#' "
        "/etc/systemd/system/his-trial-guard.service; "
        "systemctl daemon-reload; "
        "systemctl cat his-trial-guard.service"
    )

    print("=" * 72)
    print("## 重新挂载 /mnt/boot 并确认内容")
    broot.srun("umount /mnt/boot 2>/dev/null; mount /mnt/boot; findmnt /mnt/boot; ls -l /mnt/boot/")

    print("=" * 72)
    print("## 测试 wget -c -O 是否可用 (断点续传是关键)")
    broot.srun(
        "cd /tmp && rm -f c1 c2; "
        "wget -q -T 15 -O c1 http://192.168.10.17:8899/boot.scr && echo '普通 -O OK'; "
        "wget -q -T 15 -c -O c2 http://192.168.10.17:8899/boot.scr && echo '-c -O OK' || echo '-c -O 不支持'; "
        "md5sum c1 c2 2>&1"
    )

    print("=" * 72)
    print("## 空间确认")
    broot.srun("df -h /mnt/boot")


main()
