#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rtc_wake_test.py —— 安全测试 RTC 闹钟机制（不真的挂起）

背景
----
用户要求：跑 20 分钟（80多度）就关机休息一段再重启。
要做到【自动】重启，必须有一个"关机后还能把板子叫醒"的机制。

这块板子有：
  · rtc-pcf8563  (/dev/rtc0)  —— 带闹钟的 I2C RTC
  · /sys/power/state = "freeze mem"  —— 支持挂起

本脚本【只验证闹钟寄存器能不能设、能不能读到 pending】，
不执行任何挂起/关机动作 —— 先把机制确认了，再谈自动化。

用法:
    sudo python3 rtc_wake_test.py           # 设 +90 秒闹钟，看 pending
    sudo python3 rtc_wake_test.py --clear   # 清掉闹钟
"""
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WAKEALARM = "/sys/class/rtc/rtc0/wakealarm"
RTC_PROC = "/proc/driver/rtc"


def sh(cmd, t=10):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=t)
        return p.returncode, p.stdout.decode(errors="replace").strip()
    except Exception as e:
        return -1, str(e)


def rd(path):
    try:
        return open(path).read().strip()
    except Exception as e:
        return "(读不了: %s)" % e


def show_rtc(tag):
    print("  --- %s ---" % tag)
    rc, out = sh(["cat", RTC_PROC])
    for line in out.split("\n"):
        if any(k in line for k in ("alrm_", "alarm_", "rtc_time", "rtc_date")):
            print("     " + line.strip())


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root")

    print("=" * 74)
    print(" RTC 闹钟机制安全测试（不挂起、不关机）")
    print("=" * 74)

    print("\n>>> 0. 当前状态")
    print("   /sys/power/state = %s" % rd("/sys/power/state"))
    print("   wakealarm        = %r" % rd(WAKEALARM))
    show_rtc("测试前")

    if "--clear" in sys.argv:
        with open(WAKEALARM, "w") as f:
            f.write("0")
        print("\n 已清除闹钟")
        print("   wakealarm = %r" % rd(WAKEALARM))
        show_rtc("清除后")
        return

    print("\n>>> 1. 设一个 +90 秒的闹钟")
    when = int(time.time()) + 90
    try:
        with open(WAKEALARM, "w") as f:
            f.write(str(when))
        print("   已写入 %d (%s)" % (when, time.strftime("%H:%M:%S", time.localtime(when))))
    except Exception as e:
        print("   ★ 写入失败: %s" % e)
        print("   ⇒ 这个 RTC 不支持从用户态设闹钟，自动轮休要走别的路")
        return

    time.sleep(1)
    print("   wakealarm 读回 = %r" % rd(WAKEALARM))
    show_rtc("设闹钟后")

    print("\n>>> 2. 判断")
    rc, out = sh(["cat", RTC_PROC])
    pending = "alrm_pending\t: yes" in out
    irq = "alarm_IRQ\t: yes" in out
    alarm_set = rd(WAKEALARM) not in ("", "0", "None")
    print("   闹钟寄存器已设: %s" % ("✓" if alarm_set else "✗"))
    print("   alrm_pending  : %s" % ("yes" if pending else "no"))
    print("   alarm_IRQ     : %s" % ("yes" if irq else "no"))

    print("\n>>> 3. 清掉闹钟（避免影响后续）")
    try:
        with open(WAKEALARM, "w") as f:
            f.write("0")
        print("   已清除")
    except Exception as e:
        print("   清除失败: %s" % e)

    print()
    print("=" * 74)
    if alarm_set:
        print(" ★ 结论：RTC 闹钟【可以设置】")
        print("   ⇒ 理论上支持「关机/挂起 -> RTC 到时唤醒」的自动轮休")
        print("   ⇒ 但『能不能真的唤醒』还要实机验证一次（有风险，见下）")
        print()
        print(" ⚠️ 风险提示：真验证需要挂起或关机，如果唤醒失败，")
        print("    板子会停在那儿直到物理断电重启。")
    else:
        print(" ★ 结论：这个 RTC【设不了闹钟】")
        print("   ⇒ 自动轮休做不了，只能：")
        print("      a) 到温度上限时写日志 + 通知，等人工重启")
        print("      b) 用硬件看门狗做定时复位（如果它能在 halt 后继续跑）")


if __name__ == "__main__":
    main()
