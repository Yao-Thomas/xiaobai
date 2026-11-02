#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_guard.py —— 修自愈服务的路径不一致, 并在他的内核上当场跑一遍验证

发现: 脚本装成了 /usr/local/bin/his_trial_guard.sh (下划线),
      unit 里写的是 /usr/local/bin/his-trial-guard.sh (连字符)
      -> systemd 203/EXEC, 自愈服务从来没执行过。
      这次是网络自己通了才没事; 没通就没有自动退回。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
GUARD = r"D:\ubuntu_iso\his_trial_guard.sh"
CANON = "/usr/local/bin/his-trial-guard.sh"


def main():
    board.HOST = IP

    print("=" * 72)
    print("## 现状")
    broot.srun("ls -l /usr/local/bin/his*; echo ---; grep -n ExecStart "
               "/etc/systemd/system/his-trial-guard.service")

    print("=" * 72)
    print("## 统一成连字符版本 (和 unit 一致), 删掉下划线那份")
    broot.put_root(GUARD, CANON, "0755")
    broot.srun("rm -f /usr/local/bin/his_trial_guard.sh; "
               "chmod +x " + CANON + "; "
               "sh -n " + CANON + " && echo '语法 OK'; "
               "ls -l " + CANON + "; "
               "grep -n ExecStart /etc/systemd/system/his-trial-guard.service; "
               "systemctl daemon-reload; "
               "systemctl reset-failed his-trial-guard.service 2>&1; true")

    print("=" * 72)
    print("## 网关可达性 (自愈服务靠这个判断有没有网)")
    broot.srun("ping -c 2 -W 2 192.168.10.1; ip -4 -o addr show | awk '$2 ~ /^wl/ {print $4}'")

    print("=" * 72)
    print("## 当场跑一遍 guard (现在就是他的内核, 应该: 建目录 -> 写报告 -> 看到网 -> 退出0)")
    out, _ = broot.srun("time " + CANON + "; echo \"guard_rc=$?\"", timeout=600)
    print(out)

    print("=" * 72)
    print("## 报告内容")
    broot.srun("ls -l /root/his_trial/; echo '================'; "
               "head -80 /root/his_trial/report_*.txt")


main()
