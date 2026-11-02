#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_net.py —— 网络状态 + 连通性测试"""
import os, time, subprocess

def sh(cmd, t=8):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT,
                                       timeout=t).decode(errors="replace")
    except Exception as ex:
        return ""

def wlan_name():
    try:
        for n in sorted(os.listdir("/sys/class/net")):
            if n.startswith("wl"):
                return n
    except Exception:
        pass
    return "wlan0"

def net_info():
    w = wlan_name()
    ip = gw = mac = ssid = sig = "N/A"
    try:
        mac = open("/sys/class/net/%s/address" % w).read().strip()
    except Exception:
        pass
    out = sh("ip -4 addr show %s" % w)
    for tok in out.replace("/", " ").split():
        if tok.count(".") == 3 and not tok.startswith("255"):
            ip = tok
            break
    out = sh("ip route")
    for line in out.splitlines():
        if line.startswith("default"):
            p = line.split()
            if "via" in p:
                gw = p[p.index("via") + 1]
            break
    out = sh("iwconfig %s" % w, 3)
    for line in out.splitlines():
        if "ESSID:" in line:
            rest = line.split("ESSID:", 1)[1].strip()
            if rest.startswith('"'):
                ssid = rest[1:].split('"', 1)[0]      # 只取引号里的部分
            else:
                ssid = rest.split()[0] if rest.split() else "N/A"
        if "Signal level=" in line:
            sig = line.split("Signal level=")[1].split()[0]
    return w, ip, gw, mac, ssid, sig

def draw(scr, info, ping_result):
    w, ip, gw, mac, ssid, sig = info
    scr.clear((21, 21, 21))
    scr.rect([0, 0, scr.w, 60], fill=(39, 39, 39))
    scr.rect([0, 58, scr.w, 62], fill=(60, 150, 190))
    scr.rrect([10, 8, 130, 52], 10, fill=(50, 70, 90))
    scr.text((70, 30), "< 返回", 22, (255, 255, 255), cn=True, anchor="mm")
    scr.text((150, 30), "网络状态", 26, (238, 238, 238), cn=True, anchor="lm")

    y = 88
    rows = [("无线网卡", w), ("IP 地址", ip), ("网关", gw),
            ("MAC", mac), ("热点 SSID", ssid), ("信号强度", sig)]
    for k, v in rows:
        scr.rrect([30, y, scr.w - 30, y + 48], 10, fill=(35, 35, 35))
        scr.text((48, y + 24), k, 22, (120, 200, 230), cn=True, anchor="lm")
        scr.text((scr.w - 48, y + 24), v, 22, (244, 244, 244), anchor="rm", mono=True)
        y += 56

    # 测试按钮
    scr.rrect([30, y + 6, 330, y + 60], 12, fill=(40, 130, 200))
    scr.text((180, y + 33), "测试联网", 24, (255, 255, 255), cn=True, anchor="mm")
    if ping_result:
        scr.rrect([350, y + 6, scr.w - 30, y + 60], 12, fill=(28, 60, 44))
        scr.text((370, y + 33), ping_result[:60], 20, (140, 240, 180), anchor="lm")
    scr.text((scr.w // 2, scr.h - 22), "点“测试联网”试 ping 一下", 18,
             (100, 150, 180), cn=True, anchor="mm")

def run(scr, touch):
    info = net_info()
    ping_result = ""
    dirty = True
    last = 0
    while True:
        if dirty or time.time() - last > 10:
            info = net_info()
            draw(scr, info, ping_result)
            scr.flush()
            dirty = False
            last = time.time()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if 0 <= x <= 140 and 0 <= y <= 62:
                return
            if 30 <= y <= 620 and 30 <= x <= 330 and y > 500:
                scr.rrect([30, 540, 330, 594], 12, fill=(120, 90, 20))
                scr.text((180, 567), "测试中...", 24, (255, 255, 255), cn=True, anchor="mm")
                scr.flush()
                out = sh("ping -c 2 -W 3 223.5.5.5", 15)
                if "0% packet loss" in out:
                    ping_result = "成功: 2/2 包, 网络正常"
                elif "1 received" in out or "1 packets received" in out:
                    ping_result = "部分丢包, 网络不稳"
                else:
                    ping_result = "失败: 连不上外网"
                dirty = True
        time.sleep(0.05)
