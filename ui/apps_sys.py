#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_sys.py —— 系统信息"""
import os, time, platform
from fbui import font

def cpu_percent():
    def snap():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        return sum(v), idle
    try:
        t1, i1 = snap()
        time.sleep(0.35)
        t2, i2 = snap()
        dt, di = t2 - t1, i2 - i1
        return 0 if dt == 0 else int(100 * (dt - di) / dt)
    except Exception:
        return 0

def meminfo():
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                d[k] = int(v.strip().split()[0])
    except Exception:
        pass
    d.setdefault("MemTotal", 1)
    d.setdefault("MemAvailable", 0)
    return d

def board_temp():
    for p in ("/sys/bus/iio/devices/iio:device0/in_temp0_raw",
              "/sys/devices/soc0/amba/f8007100.adc/iio:device0/in_temp0_raw"):
        try:
            raw = int(open(p).read().strip())
            return (raw * 503.975 / 4096.0) - 273.15
        except Exception:
            pass
    return None

def draw(scr, cpu, mem, extra):
    scr.clear((16, 22, 42))
    scr.rect([0, 0, scr.w, 60], fill=(30, 40, 68))
    scr.rect([0, 58, scr.w, 62], fill=(70, 110, 180))
    scr.rrect([10, 8, 130, 52], 10, fill=(60, 70, 100))
    scr.text((70, 30), "< 返回", 22, (255, 255, 255), cn=True, anchor="mm")
    scr.text((150, 30), "系统信息", 26, (235, 240, 255), cn=True, anchor="lm")

    y = 88
    lines = [
        ("内核版本", extra["kernel"]),
        ("主机名", extra["host"]),
        ("运行时长", extra["uptime"]),
        ("CPU 占用", "%d %%" % cpu),
        ("内存使用", "%d MB / %d MB  (%d%%)" % (mem["used"], mem["total"], mem["pct"])),
        ("磁盘使用", "%s / %s  (%d%%)" % (extra["dused"], extra["dtotal"], extra["dpct"])),
        ("无线网卡", extra["wlan"]),
        ("IP 地址", extra["ip"]),
        ("板子温度", extra["temp"]),
    ]
    for k, v in lines:
        scr.rrect([30, y, scr.w - 30, y + 46], 10, fill=(28, 38, 66))
        scr.text((48, y + 23), k, 22, (150, 180, 230), cn=True, anchor="lm")
        scr.text((scr.w - 48, y + 23), v, 22, (235, 245, 255), anchor="rm", mono=True)
        y += 54

def run(scr, touch):
    while True:
        cpu = cpu_percent()
        m = meminfo()
        mem = {"total": m["MemTotal"] // 1024,
               "used": (m["MemTotal"] - m["MemAvailable"]) // 1024}
        mem["pct"] = int(100 * mem["used"] / max(1, mem["total"]))
        try:
            st = os.statvfs("/")
            dtotal_mb = st.f_blocks * st.f_frsize // (1024 * 1024)
            dfree_mb = st.f_bavail * st.f_frsize // (1024 * 1024)
            dused_mb = dtotal_mb - dfree_mb
        except Exception:
            dtotal_mb = dfree_mb = dused_mb = 0
        up = 0.0
        try:
            with open("/proc/uptime") as f:
                up = float(f.readline().split()[0])
        except Exception:
            pass
        ip, wlan = "-", "-"
        try:
            for n in os.listdir("/sys/class/net"):
                if n.startswith("wl"):
                    wlan = n
                    import subprocess
                    out = subprocess.check_output(["ip", "-4", "addr", "show", n]).decode()
                    for tok in out.split():
                        if tok.startswith("192.") or tok.startswith("10."):
                            ip = tok
                            break
        except Exception:
            pass
        t = board_temp()
        extra = {
            "kernel": platform.release(),
            "host": platform.node(),
            # 用纯 ASCII, 因为值那一列用的是等宽字体(没有中文)
            "uptime": "%dh %dm" % (up // 3600, (up % 3600) // 60),
            "dused": "%.1fG" % (dused_mb / 1024.0),
            "dtotal": "%.1fG" % (dtotal_mb / 1024.0),
            "dpct": int(100 * dused_mb / max(1, dtotal_mb)),
            "wlan": wlan, "ip": ip,
            "temp": ("%.1f C" % t) if t else "N/A",
        }
        draw(scr, cpu, mem, extra)
        scr.text((scr.w // 2, scr.h - 22), "点“返回”回到桌面  ·  每 2 秒自动刷新",
                 18, (120, 145, 190), cn=True, anchor="mm")
        scr.flush()
        # 等 2 秒, 期间可点返回
        end = time.time() + 2.0
        while time.time() < end:
            ev = touch.poll()
            if ev:
                _, x, y = ev
                if 0 <= x <= 140 and 0 <= y <= 62:
                    return
            time.sleep(0.05)
