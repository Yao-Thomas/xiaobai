#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup_boot.py —— 动手之前: 把启动分区全量拉到本地 + 查 mkimage

备份到 D:\\总文件夹\\FPGA2026\\_boot_backup_<时间>\\
"""
import hashlib
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

BK = os.path.join(r"D:\总文件夹\FPGA2026",
                  "_boot_backup_" + time.strftime("%m%d_%H%M%S"))


def rr(script, tag, timeout=300):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    board.put(local, "/tmp/_%s.sh" % tag)
    return board.run("echo %s | sudo -S -p '' bash /tmp/_%s.sh" % (board.PASS, tag),
                     timeout=timeout)


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    board.HOST = board.find_host(verbose=False)
    if not board.HOST:
        raise SystemExit("板子不在线")
    os.makedirs(BK, exist_ok=True)
    print("备份目录: %s" % BK)

    # 1. 挂载并列出
    out, _ = rr("mkdir -p /mnt/boot; mountpoint -q /mnt/boot || mount "
                "/dev/mmcblk0p1 /mnt/boot; ls -l /mnt/boot/", "mnt")
    print(out)

    # 2. 逐个下载
    out, _ = rr("ls /mnt/boot/", "ls")
    names = [n.strip() for n in out.splitlines()
             if n.strip() and " " not in n.strip()]
    print("待备份 %d 项" % len(names))
    for n in names:
        if n in ("System Volume Information",):
            continue
        try:
            board.get("/mnt/boot/" + n, os.path.join(BK, n))
            lp = os.path.join(BK, n)
            # 远端 md5
            o, _ = rr("md5sum /mnt/boot/%s" % n, "md5")
            rmd5 = o.split()[0] if o.split() else "?"
            lmd5 = md5(lp)
            ok = "OK " if rmd5 == lmd5 else "✗✗ "
            print("  %s%-32s %10d  %s" % (ok, n, os.path.getsize(lp), lmd5))
        except Exception as e:
            print("  !! %-32s 下载失败: %s" % (n, e))

    # 3. 查 mkimage
    out, _ = rr("which mkimage; mkimage -l /mnt/boot/boot.scr 2>&1 | head -8; "
                "echo ---; ls -l /mnt/boot/boot.scr", "mk")
    print("\n=== mkimage / boot.scr 信息 ===")
    print(out)

    # 4. 保存 boot.scr 头 (做新脚本时照抄)
    try:
        board.get("/mnt/boot/boot.scr", os.path.join(BK, "boot.scr"))
        h = open(os.path.join(BK, "boot.scr"), "rb").read()[:64]
        print("boot.scr 头部 64 字节:")
        print("  " + h.hex(" "))
    except Exception as e:
        print("  取 boot.scr 失败: %s" % e)

    rr("umount /mnt/boot 2>/dev/null; true", "um")
    print("\n备份完成 -> %s" % BK)


if __name__ == "__main__":
    main()
