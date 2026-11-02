#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 16 个应用**逐个打开 -> 点退出 -> 再打开**，验证每个都能退出来。

做法：注入点击（/tmp/ui_tap）。
  1. 点图标 -> 日志里应出现 "打开: XXX"
  2. 点 (70,30) —— 所有应用的退出键判定区都覆盖这个点
  3. 再点同一个图标 -> 日志里应**再次**出现 "打开: XXX"
     出现 = 第 2 步真的退出来了；没出现 = 还卡在应用里
  4. 万一卡住，重启桌面再继续（不能让它污染后面的用例）
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

PAGE1 = [("扫雷", 187, 152), ("计算器", 317, 152), ("画板", 447, 152),
         ("文件", 577, 152), ("图片", 707, 152), ("命令面板", 837, 152),
         ("示波器", 187, 292), ("系统信息", 317, 292), ("WiFi", 447, 292),
         ("关于", 577, 292), ("壁纸", 707, 292), ("小说", 837, 292)]
PAGE2 = [("死神VS火影", 187, 152), ("我的世界", 317, 152),
         ("浏览器", 447, 152), ("GPU 测试台", 577, 152)]

DOCK_HOME = (292, 564)
DOCK_APPS = (380, 564)
DOT2 = (523, 522)              # 图标页第 2 页的页码点
BACK = (70, 30)                # 通用退出键位置


def sh(cmd, sudo=False, timeout=180):
    if sudo:
        out, _ = broot.srun(cmd, timeout=timeout, quiet=True)
    else:
        out, _ = board.run(cmd, timeout=timeout, quiet=True)
    return out


def marks():
    try:
        return int(sh("wc -l < %s" % LOG).strip().split()[0])
    except Exception:
        return 0


def since(n):
    return sh("tail -n +%d %s" % (n + 1, LOG))


def tap(x, y, wait=1.5):
    sh("echo '%d,%d' > /tmp/ui_tap" % (x, y))
    time.sleep(wait)


def restart_desktop():
    sh("systemctl restart zynq-desktop", sudo=True)
    time.sleep(19)


def goto_icon_page(n):
    """回到首页再进图标页；n=1 或 2"""
    tap(*DOCK_HOME, wait=1.5)
    tap(*DOCK_APPS, wait=2.0)
    time.sleep(1.2)
    if n == 2:
        tap(*DOT2, wait=1.8)


def check(apps, page):
    bad = []
    for name, x, y in apps:
        n0 = marks()
        tap(x, y, wait=1.8)
        if ("打开: %s" % name) not in since(n0):
            print("   %-12s !! 打不开" % name)
            bad.append((name, "打不开"))
            restart_desktop()
            goto_icon_page(page)
            continue
        # 退出
        tap(*BACK, wait=1.6)
        # 再打一次
        n1 = marks()
        tap(x, y, wait=1.8)
        ok = ("打开: %s" % name) in since(n1)
        print("   %-12s %s" % (name, "退出正常" if ok else "!! 退不出来（卡住了）"))
        if ok:
            tap(*BACK, wait=1.5)
        else:
            bad.append((name, "退不出来"))
            restart_desktop()
            goto_icon_page(page)
    return bad


def main():
    print("HOST =", board.HOST)

    print("\n=== 1) 部署 apps_browser.py（加了「桌面」按钮）")
    local = os.path.join(UI, "apps_browser.py")
    board.put(local, "/tmp/_dep_apps_browser.py")
    broot.srun("install -o zynq -g zynq -m 0644 /tmp/_dep_apps_browser.py "
               "/home/zynq/ui/apps_browser.py", quiet=True)
    print("   ->/home/zynq/ui/apps_browser.py")

    print("\n=== 2) 重启桌面")
    restart_desktop()
    print("   ", sh("systemctl is-active zynq-desktop").strip())

    bad = []

    print("\n=== 3) 图标页第 1 屏（12 个）")
    goto_icon_page(1)
    bad += check(PAGE1, 1)

    print("\n=== 4) 图标页第 2 屏（4 个）")
    goto_icon_page(2)
    bad += check(PAGE2, 2)

    print("\n=== 5) 收尾：回首页")
    tap(*BACK, wait=1.2)
    tap(*DOCK_HOME, wait=1.5)
    sh("cd /home/zynq/ui && python3 shot_board.py /home/zynq/proof_home3.png",
       sudo=True)
    try:
        board.get("/home/zynq/proof_home3.png",
                  os.path.join(HERE, "proof_home3.png"))
        print("   已下载 proof_home3.png")
    except Exception as e:
        print("   截图下载失败:", e)

    print("\n" + "=" * 62)
    if bad:
        print("有问题的：")
        for n, why in bad:
            print("   - %-12s %s" % (n, why))
    else:
        print("16 个应用全部：能打开、能退出")
    print("=" * 62)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
