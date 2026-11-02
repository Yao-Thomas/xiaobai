#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_B.py —— 阶段 B-2: 真正开试

  1. 装上带屏幕取证的 his-trial-guard
  2. touch /home/zynq/.guard_pause  (暂停我们自己的黑屏守护, 别让它误判重启打断试用)
  3. 确认没有 use_ours.flag
  4. touch /etc/his-trial-armed     (让 his-trial-guard 在试用那一跳启动)
  5. mv image.ub.part -> image.ub   <-- 这一下才是"开试"的扳机
  6. 重启, 然后盯 8 分钟

三种结局:
  A. 他的内核起来且 WiFi 通 -> SSH 能进, uname 是他的 -> 成功
  B. 他的内核起来但没网     -> 240s 后自愈服务重启 -> 回到我们系统 -> 读 /root/his_trial/
  C. 他的内核 panic         -> panic=10 自动重启 -> flag 已置位 -> 回到我们系统
"""
import hashlib
import io
import socket
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
GUARD = r"D:\ubuntu_iso\his_trial_guard.sh"
OUR_UTS = "#1 SMP PREEMPT Thu Sep 14 08:39:17 UTC 2023"


def port_open(t=2):
    try:
        s = socket.create_connection((IP, 22), timeout=t)
        s.close()
        return True
    except Exception:
        return False


def ssh(cmd, timeout=30):
    board.HOST = IP
    try:
        out, err = board.run(cmd, timeout=timeout, quiet=True)
        return out
    except Exception as e:
        return "SSHERR %s" % e


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)

    print("=" * 72)
    print("## 1) 装带屏幕取证的 guard")
    broot.put_root(GUARD, "/usr/local/bin/his_trial_guard.sh", "0755")
    broot.srun("chmod +x /usr/local/bin/his_trial_guard.sh; ls -l /usr/local/bin/his_trial_guard.sh; "
               "sh -n /usr/local/bin/his_trial_guard.sh && echo '语法 OK'")

    print("=" * 72)
    print("## 2) 暂停我们自己的黑屏守护")
    broot.srun("touch /home/zynq/.guard_pause; ls -l /home/zynq/.guard_pause")

    print("=" * 72)
    print("## 3-4) 标记置位")
    broot.srun("touch /etc/his-trial-armed; rm -f /mnt/boot/use_ours.flag; "
               "ls -l /etc/his-trial-armed; ls -l /mnt/boot/use_ours.flag 2>&1; true")

    print("=" * 72)
    print("## 5) 落下 image.ub  (= 开试扳机)")
    broot.srun("set -e; cd /mnt/boot; "
               "md5sum image.ub.part; "
               "mv -f image.ub.part image.ub; sync; "
               "ls -l image.ub; md5sum image.ub; "
               "echo '--- 最终 /mnt/boot ---'; ls -l")

    print("=" * 72)
    print("## 6) 重启, 开始盯")
    before = ssh("uptime; uname -v")
    print("重启前: " + before.strip().replace("\n", " | "))

    try:
        ssh("sudo -n reboot", timeout=10)
    except Exception:
        pass

    t0 = time.time()
    saw_his = False
    saw_our_again = False
    offline_seen = False
    log = []

    while time.time() - t0 < 480:
        time.sleep(10)
        dt = time.time() - t0
        if not port_open():
            offline_seen = True
            print("  %5.0fs  SSH 不通" % dt)
            continue
        u = ssh("uname -v").strip()
        if not u or u.startswith("SSHERR"):
            print("  %5.0fs  端口开但还登不上" % dt)
            continue
        if u == OUR_UTS:
            if offline_seen:
                print("  %5.0fs  >>> 已回到我们自己的系统" % dt)
                saw_our_again = True
                break
            print("  %5.0fs  还是我们自己的系统" % dt)
        else:
            print("  %5.0fs  >>> 跑的是他的内核: %s" % (dt, u))
            log.append(u)
            saw_his = True
            break

    print()
    print("=" * 72)
    print("## 结果")
    if saw_his:
        print("!!! 他的系统起来了并且有网 —— 直接进去看")
        print(ssh("uname -a; cat /proc/cmdline; ip -br addr; lsmod | head -20; "
                  "cat /proc/fb; ls /dev/fb* /dev/dri/ 2>&1; "
                  "dmesg | tail -40").strip())
    elif saw_our_again:
        print("他的系统没能自己带起网络, 已自动退回我们的系统。取现场报告:")
        broot.srun("ls -l /root/his_trial/; "
                   "echo '========== REPORT =========='; "
                   "cat /root/his_trial/report_*.txt | head -200")
    else:
        print("!! 8 分钟没结论, 当前状态:")
        print(broot.srun("uptime; uname -v; ls -l /root/his_trial/ 2>&1", quiet=False))

    return 0


main()
