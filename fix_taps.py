#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署首页/桌面点击修复 + 用注入点击做回归验证。

修的三个 bug：
  B1  图标页（第 2 屏）12 个图标**全部点不动** —— 首页 6 张卡片的矩形几乎盖满
      整个屏幕，desktop.py 在图标页遇到 ("card",…) 就 return，把点击吃掉了。
      → 图标页只认 dock / 全部应用 / 页码点，忽略 card。
  B2  点「天气」卡跳到 WiFi —— card_action 里 "weather" 和 "network" 写在一个分支。
      → 有天气数据就刷新+弹详情；卡片显示"未联网"时才去开 WiFi。
  B3  「最近使用」卡右边一列两个图标点不到 —— draw_recent 和 hit() 各写了一套坐标。
      → 抽成 recent_centers()，画和点用同一份。
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402
import broot                       # noqa: E402

UI = os.path.join(HERE, "ui")
LOG = "/var/log/zynq-desktop.log"

# 图标页格子中心: COLS=6, ICON_W=96, ICON_H=96, GAP_X=34, GAP_Y=44, ICON_TOP=104
#   ox = (1024 - (6*96+5*34))//2 = 139
ICON = [(139 + c * 130 + 48, 104 + r * 140 + 48)
        for r in range(2) for c in range(6)]

# Dock: bw=6*88+24=552, bx0=(1024-552)//2=236, items x=248+i*88, y=536..592
DOCK = [(248 + i * 88 + 44, 564) for i in range(6)]

WEATHER_CARD_XY = (635, 150)       # 天气卡中心
RECENT = [(824, 360), (938, 360), (824, 448), (938, 448)]   # 最近使用 4 个图标


def sh(cmd, sudo=False, timeout=180):
    if sudo:
        out, err = broot.srun(cmd, timeout=timeout, quiet=True)
    else:
        out, err = board.run(cmd, timeout=timeout, quiet=True)
    return out


def log_marks():
    out = sh("wc -l < %s" % LOG)
    try:
        return int(out.strip().split()[0])
    except Exception:
        return 0


def log_since(n):
    return sh("tail -n +%d %s" % (n + 1, LOG))


def tap(x, y, wait=1.3):
    sh("echo '%d,%d' > /tmp/ui_tap" % (x, y))
    time.sleep(wait)


def main():
    print("HOST =", board.HOST)

    print("\n=== 1) 部署")
    for fn in ("home.py", "desktop.py"):
        local = os.path.join(UI, fn)
        tmp = "/tmp/_dep_" + fn
        board.put(local, tmp)
        broot.srun("install -o zynq -g zynq -m 0644 %s /home/zynq/ui/%s"
                   % (tmp, fn), quiet=True)
        print("   ->/home/zynq/ui/%s" % fn)

    print("\n=== 2) 重启桌面")
    sh("systemctl restart zynq-desktop", sudo=True)
    time.sleep(20)
    print("   状态:", sh("systemctl is-active zynq-desktop").strip())

    fails = []
    BACK = (60, 30)               # 应用左上角的返回键 fbui.back_hit = [10,8,130,52]

    def open_then_back(x, y, pat, wait=1.8, retry=True):
        """点一下，看日志里有没有 pat；有就按返回键退出应用。

        第一次点击偶尔会被"刚翻页还在重绘"吃掉，所以没反应就再点一次。
        """
        for attempt in range(2 if retry else 1):
            n0 = log_marks()
            tap(x, y, wait=wait + (0.8 if attempt else 0))
            new = log_since(n0)
            m = re.search(pat, new)
            if m:
                tap(*BACK, wait=1.5)      # 退出应用，回到图标页
                return m
        return None

    # ---------------- B1: 图标页 12 个图标都能点 ----------------
    print("\n=== 3) B1 回归：图标页 12 个图标")
    tap(*DOCK[1], wait=2.0)           # Dock「应用」-> 图标页
    time.sleep(2.0)                   # 冷启动第一帧要建图标缓存，等一会儿
    ok = 0
    for i, (x, y) in enumerate(ICON):
        m = open_then_back(x, y, r"打开:\s*(\S+)")
        if m:
            ok += 1
            name = m.group(1)
        else:
            name = "--没反应--"
        print("   格 %2d (%4d,%3d) -> %s" % (i + 1, x, y, name))
    print("   >>> 12 格里 %d 格能点开" % ok)
    if ok < 12:
        fails.append("B1: 只有 %d/12 个图标能点开" % ok)

    # ---------------- B2: 天气卡不再跳 WiFi ----------------
    print("\n=== 4) B2 回归：点天气卡")
    tap(*DOCK[0], wait=1.5)           # 回首页
    n0 = log_marks()
    tap(*WEATHER_CARD_XY, wait=3.2)
    new = log_since(n0)
    print("   新增日志:")
    for ln in new.strip().split("\n"):
        if ln.strip():
            print("     " + ln)
    if "[weather] 点天气卡" in new:
        print("   >>> OK: 天气卡走的是刷新+详情")
    elif "apps_wifi" in new or "WiFi" in new:
        print("   >>> !! 还是会跳 WiFi")
        fails.append("B2: 点天气仍然打开 WiFi")
    else:
        print("   >>> !! 天气卡没反应")
        fails.append("B2: 点天气卡没有任何反应")

    # ---------------- B3: 最近使用卡 4 个图标 ----------------
    print("\n=== 5) B3 回归：最近使用卡 4 个图标")
    ok3 = 0
    for i, (x, y) in enumerate(RECENT):
        m = open_then_back(x, y, r"\[recent\] 打开:\s*(\S+)")
        if m:
            ok3 += 1
            nm = m.group(1)
        else:
            nm = "--没反应--"
        print("   图标 %d (%4d,%3d) -> %s" % (i + 1, x, y, nm))
    print("   >>> 4 个里 %d 个能点开" % ok3)
    if ok3 < 4:
        fails.append("B3: 只有 %d/4 个最近使用图标能点开" % ok3)

    # ---------------- Dock 6 个按钮 ----------------
    print("\n=== 6) 回归：Dock 6 个按钮")
    tap(*DOCK[0], wait=1.5)
    for i, (x, y) in enumerate(DOCK):
        n0 = log_marks()
        tap(x, y, wait=1.8)
        new = log_since(n0)
        m = re.search(r"\[dock\]\s*(\S+)", new)
        print("   Dock %d (%4d,%3d) -> %s"
              % (i, x, y, m.group(1) if m else "--没反应--"))
        tap(*BACK, wait=1.2)
        tap(*DOCK[0], wait=1.3)

    print("\n=== 7) 收尾：回首页 + 截图")
    tap(*DOCK[0], wait=1.5)
    sh("cd /home/zynq/ui && python3 shot_board.py /home/zynq/shot_fix_home.png",
       sudo=True)
    tap(*DOCK[1], wait=1.8)
    sh("cd /home/zynq/ui && python3 shot_board.py /home/zynq/shot_fix_p2.png",
       sudo=True)
    for r in ("/home/zynq/shot_fix_home.png", "/home/zynq/shot_fix_p2.png"):
        try:
            board.get(r, os.path.join(HERE, os.path.basename(r)))
            print("   已下载", os.path.basename(r))
        except Exception as e:
            print("   截图下载失败 %s: %s" % (r, e))

    print("\n" + "=" * 60)
    if fails:
        print("还有问题：")
        for f in fails:
            print("   -", f)
    else:
        print("全部通过：图标页 12/12、天气卡正确、最近使用 4/4")
    print("=" * 60)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
