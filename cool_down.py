#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cool_down.py —— 开机时的"冷却暂停"

════════════════════════════════════════════════════════════════════
它解决什么问题
════════════════════════════════════════════════════════════════════
温度守护在 96°C 时会重启板子。但重启只花 ~40 秒，板子还没凉就又开始
跑桌面了，等于白重启。

而这块板子 poweroff 之后醒不过来（实测：RTC 闹钟叫不醒、DTR/RTS 复位
不了、串口全静默），所以【不能靠关机来降温】。

⇒ 折中方案：重启，但在开机早期"磨蹭"几分钟。
   那段时间只有最小系统（systemd、网络）在跑，桌面/音频都还没起，
   能比满载时凉一些。等暂停结束再让桌面起来。

════════════════════════════════════════════════════════════════════
怎么用
════════════════════════════════════════════════════════════════════
由 thermal-cooldown.service 在 graphical.target 之前调用：
    ExecStart=/usr/bin/python3 /home/zynq/cool_down.py

它读 /var/lib/thermal/cool_down（温度守护重启前写的）：
    第一行 = 暂停多少分钟
    第二行 = 触发时的温度
读完就删掉，保证只生效一次（不然每次开机都暂停）。

没有标志文件时它立即返回，不影响正常开机。

也可以手动用：
    sudo python3 cool_down.py --mins 5     # 强制暂停 5 分钟（测试用）
    sudo python3 cool_down.py --status     # 看有没有待处理的冷却
"""
import argparse
import datetime
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FLAG = "/var/lib/thermal/cool_down"
LOGF = "/var/log/thermal_guard.log"


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOGF, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mins", type=float, default=None, help="强制暂停这么多分钟")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        if os.path.exists(FLAG):
            print("有待处理的冷却暂停:")
            print(open(FLAG).read())
        else:
            print("没有待处理的冷却暂停")
        return 0

    mins = a.mins
    temp = None
    if mins is None:
        if not os.path.exists(FLAG):
            return 0                      # 正常开机，直接放行
        try:
            parts = open(FLAG).read().split()
            mins = float(parts[0]) if parts else 5.0
            temp = float(parts[1]) if len(parts) > 1 else None
        except Exception as e:
            log("冷却标志读取失败(%s)，按默认 5 分钟处理" % e)
            mins = 5.0
        # ★ 读完就删，只生效一次
        try:
            os.remove(FLAG)
        except OSError:
            pass

    if mins <= 0:
        return 0

    secs = int(mins * 60)
    log("=" * 60)
    log("★ 冷却暂停开始：%.1f 分钟" % mins)
    if temp is not None:
        log("   触发温度：%.1f°C" % temp)
    log("   这段时间只有最小系统在跑（桌面/音频还没起）")
    log("=" * 60)

    t0 = time.time()
    last_report = 0
    while time.time() - t0 < secs:
        left = secs - (time.time() - t0)
        # 每分钟报一次进度（也顺便读一下温度，好看出有没有在降）
        if time.time() - t0 - last_report >= 60:
            last_report = time.time() - t0
            t = None
            try:
                raw = int(open("/sys/bus/iio/devices/iio:device0/in_temp0_raw").read())
                sc = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_scale").read())
                of = float(open("/sys/bus/iio/devices/iio:device0/in_temp0_offset").read())
                t = (raw + of) * sc / 1000.0
            except Exception:
                pass
            log("   冷却中… 还剩 %.0f 秒%s" %
                (left, ("   当前温度 %.1f°C" % t) if t is not None else ""))
        time.sleep(2)

    log("冷却暂停结束，继续正常启动")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
