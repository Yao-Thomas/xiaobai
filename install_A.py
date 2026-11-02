#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_A.py —— 阶段 A: 装自愈服务 + 换 boot.scr (不碰 image.ub)

顺序是刻意安排的:
  老 boot.scr 里 `if test -e ... /image.ub; then fatload; bootm; exit;` 是
  无条件 + exit 的。只要 FAT 上出现半个 image.ub 时重启, bootm 失败后
  u-boot 会永远停住, 而我们没有串口 -> 只能拆 SD 卡。
  所以必须先把 boot.scr 换成带 flag + 回退的版本, 再放 image.ub。

做完这一步重启一次, 证明新 boot.scr 自己不会把板子弄砖。
"""
import hashlib
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

NEW_SCR = r"D:\ubuntu_iso\boot_try_his.scr"
GUARD = r"D:\ubuntu_iso\his_trial_guard.sh"
UNIT = r"D:\ubuntu_iso\his_trial_guard.service"


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def step(title, fn):
    print("=" * 72)
    print("## " + title)
    return fn()


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    if not board.HOST:
        raise SystemExit("找不到板子")

    local_md5 = md5f(NEW_SCR)
    print("新 boot.scr: %d 字节 md5=%s" % (os.path.getsize(NEW_SCR), local_md5))

    step("前置检查 (必须没有 image.ub / use_ours.flag)",
         lambda: broot.srun("ls -l /mnt/boot/image.ub /mnt/boot/use_ours.flag 2>&1; ls -l /mnt/boot/"))

    step("安装自愈服务",
         lambda: (broot.put_root(GUARD, "/usr/local/bin/his_trial_guard.sh", "0755"),
                  broot.put_root(UNIT, "/etc/systemd/system/his_trial_guard.service", "0644"),
                  broot.srun("systemctl daemon-reload; systemctl enable his-trial-guard.service 2>&1;"
                            " ls -l /usr/local/bin/his_trial_guard.sh"
                            " /etc/systemd/system/his_trial_guard.service"))[-1])

    step("上传新 boot.scr 到 FAT (先叫 .new)",
         lambda: broot.put_root(NEW_SCR, "/mnt/boot/boot.scr.new", "0755"))

    out, _ = broot.srun("md5sum /mnt/boot/boot.scr.new | cut -d' ' -f1", quiet=True)
    got = out.strip()
    print("板上 boot.scr.new md5 = %s" % got)
    if got != local_md5:
        raise SystemExit("!! md5 不符: 板上 %s != 本地 %s" % (got, local_md5))
    print(">> md5 校验通过")

    step("备份旧 boot.scr 并原子替换",
         lambda: broot.srun("set -e; cd /mnt/boot; "
                            "cp -f boot.scr boot.scr.bak_before_histrial; "
                            "mv -f boot.scr.new boot.scr; sync; "
                            "ls -l boot.scr boot.scr.bak_before_histrial; md5sum boot.scr"))

    step("最终现场",
         lambda: broot.srun("echo '--- /mnt/boot ---'; ls -l /mnt/boot/; "
                            "echo '--- flag (应不存在) ---'; ls -l /mnt/boot/use_ours.flag 2>&1; "
                            "echo '--- image.ub (应不存在) ---'; ls -l /mnt/boot/image.ub 2>&1; "
                            "echo '--- guard ---'; systemctl is-enabled his-trial-guard.service"))

    print()
    print("阶段 A 完成。板子仍在跑我们的系统, boot.scr 已换成安全版。")
    print("下一步: 重启, 验证板子能原样回来。")


main()
