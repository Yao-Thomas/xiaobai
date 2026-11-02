#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""download_B.py —— 阶段 B-1: 把 image.ub 拉到 /mnt/boot/image.ub.part 并校验

关键: 全程不出现 /mnt/boot/image.ub 这个名字。
      只有 md5 校验通过后, 才由 install_B.py 改名成 image.ub (那才是"开试"的扳机)。
"""
import hashlib
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

LOCAL = r"D:\总文件夹\FPGA2026\_ref_boot\image.ub"
LOG = "/tmp/dl_imageub.log"
PART = "/mnt/boot/image.ub.part"

REMOTE_CMD = (
    "cd /mnt/boot && rm -f image.ub.part && "
    "nohup sh -c '"
    "ok=0; "
    "for i in $(seq 1 40); do "
    "  wget -c -T 20 --tries=2 -O image.ub.part "
    "    http://192.168.10.17:8899/image.ub "
    "  && { ok=1; break; }; "
    "  echo \"--- retry $i ---\"; sleep 3; "
    "done; "
    "echo DL_DONE ok=$ok; "
    "ls -l image.ub.part; md5sum image.ub.part"
    "' > %s 2>&1 &" % LOG
)


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)

    local_md5 = hashlib.md5(open(LOCAL, "rb").read()).hexdigest()
    print("本地 image.ub: %d 字节 md5=%s" % (os.path.getsize(LOCAL), local_md5))

    broot.srun("rm -f " + LOG)
    broot.srun(REMOTE_CMD, quiet=False)
    print("已在板子后台启动下载, 日志 " + LOG)

    t0 = time.time()
    last = -1
    while time.time() - t0 < 420:
        time.sleep(6)
        out, _ = broot.srun(
            "tail -c 400 %s; echo; echo '###'; ls -l %s 2>/dev/null | awk '{print $5}'" % (LOG, PART),
            quiet=True)
        size = 0
        for line in out.strip().splitlines():
            if line.isdigit():
                size = int(line)
        print("  %5.0fs  %8d 字节" % (time.time() - t0, size))
        if "DL_DONE" in out:
            print(out)
            break
        if size == last and size > 0:
            pass
        last = size
    else:
        print("!! 超时")
        broot.srun("tail -c 800 " + LOG)
        return 1

    out, _ = broot.srun("md5sum %s | cut -d' ' -f1; stat -c %%s %s" % (PART, PART), quiet=True)
    lines = out.strip().splitlines()
    got_md5, got_size = lines[0].strip(), lines[1].strip()
    print("板上: %s 字节 md5=%s" % (got_size, got_md5))
    if got_md5 != local_md5:
        print("!! md5 不符, 不要改名")
        return 1
    print(">> image.ub.part md5 校验通过, 可以进入 install_B")
    return 0


sys.exit(main())
