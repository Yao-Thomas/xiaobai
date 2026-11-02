#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_games.py —— 客观验证两个游戏的【输入真的生效】

不用"看截图猜", 而是让程序自己写操作日志:
  我的世界: 点"放"/"挖" -> /tmp/mc_act 记下改了哪个格子、高度怎么变
  死神VS火影: 点"轻"/"重"/"必杀" -> /tmp/fight_fps 里的"玩家出招"计数
"""
import sys
import time

sys.path.insert(0, ".")
from mc_lab import Board


def mc_test(b):
    print("=" * 60)
    print("我的世界: 验证 放/挖")
    print("=" * 60)
    b.sudo("systemctl stop zynq-desktop zynq-screen-guard")
    b.sudo("pkill -9 -x python3; rm -f /tmp/mc.log /tmp/mc_act /tmp/mc_fps")
    time.sleep(1)
    b.sudo("cd /home/zynq/ui && (setsid nohup python3 run_mc.py 90 "
           ">/tmp/mc.log 2>&1 </dev/null &) ; echo go", 25)
    time.sleep(7)
    print("启动:", b.run("tail -2 /tmp/mc.log", 20).strip().replace("\n", " | "))
    print("初始 mc_act:", b.run("cat /tmp/mc_act 2>/dev/null || echo '(还没有)'", 20).strip())

    # 放 x3
    for i in range(3):
        b.tap(958, 453)          # 右下"放"
        time.sleep(1.0)
        r = b.run("cat /tmp/mc_act 2>/dev/null || echo -", 20).strip()
        print("  第%d次点【放】 -> %s" % (i + 1, r))

    # 挖 x2
    for i in range(2):
        b.tap(830, 453)          # 右下"挖"
        time.sleep(1.0)
        r = b.run("cat /tmp/mc_act 2>/dev/null || echo -", 20).strip()
        print("  第%d次点【挖】 -> %s" % (i + 1, r))

    # 换方块类型再放
    b.tap(870, 384)              # 方块选择条第 3 个(石)
    time.sleep(0.6)
    b.tap(958, 453)
    time.sleep(1.0)
    print("  选[石]后点【放】 -> %s"
          % b.run("cat /tmp/mc_act 2>/dev/null || echo -", 20).strip())
    print("  帧率:", b.run("cat /tmp/mc_fps 2>/dev/null || echo none", 20).strip())
    b.sudo("pkill -9 -f run_mc.py; pkill -9 -x python3; echo done", 25)


def fight_test(b):
    print()
    print("=" * 60)
    print("死神VS火影: 验证 轻/重/必杀")
    print("=" * 60)
    b.sudo("systemctl stop zynq-desktop zynq-screen-guard")
    b.sudo("pkill -9 -x python3; rm -f /tmp/fight.log /tmp/fight_fps")
    time.sleep(1)
    b.sudo("cd /home/zynq/ui && (setsid nohup python3 run_fight.py 90 "
           ">/tmp/fight.log 2>&1 </dev/null &) ; echo go", 25)
    time.sleep(7)

    def cnt():
        t = b.run("cat /tmp/fight_fps 2>/dev/null || echo none", 20)
        return t.strip().replace("\n", "  ")

    print("初始:", cnt())
    for label, pt in (("轻", (804, 565)), ("重", (880, 565)), ("必杀", (925, 490))):
        for k in range(3):
            b.tap(*pt)
            time.sleep(0.6)
        time.sleep(1.2)
        print("  点了 3 次【%s】 -> %s" % (label, cnt()))
    b.shot("verify_fight.png", freeze=True)
    b.sudo("pkill -9 -f run_fight.py; pkill -9 -x python3; echo done", 25)


def main():
    b = Board()
    try:
        mc_test(b)
        fight_test(b)
    finally:
        b.sudo("pkill -9 -x python3; "
               "systemctl start zynq-screen-guard zynq-desktop; echo restored", 30)
        b.close()


main()
