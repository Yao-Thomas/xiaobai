#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 PIL -> framebuffer 渲染 + 性能"""
import sys, time
sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch, font

t0 = time.time()
scr = Screen()
t1 = time.time()
print("打开屏幕耗时: %.0f ms" % ((t1 - t0) * 1000))

# 画测试图案
t0 = time.time()
scr.gradient_bg((24, 34, 68), (6, 8, 18))
t1 = time.time()
print("渐变背景: %.0f ms" % ((t1 - t0) * 1000))

t0 = time.time()
scr.rrect([40, 40, 984, 200], 16, fill=(40, 70, 130), outline=(90, 150, 230), width=3)
scr.text((70, 60), "Zynq-7020 Desktop Test", 36, (255, 255, 255), bold=True)
scr.text((70, 115), "中文测试：正点原子 领航者 ZYNQ7020  7寸屏 1024x600", 24, (200, 220, 255), cn=True)
scr.text((70, 155), "PIL render -> /dev/fb0 (24bpp BGR)   touch: GT911", 20, (150, 190, 240))
for i, c in enumerate([(230,80,80),(80,200,120),(90,150,240),(240,190,60),(200,120,230)]):
    scr.rrect([40 + i*190, 230, 200 + i*190, 340], 14, fill=c)
    scr.text((60 + i*190, 270), "BTN %d" % (i+1), 26, (20, 20, 30), bold=True)
scr.text((40, 380), "点屏幕测试触摸 ->", 28, (255, 255, 255), cn=True)
t1 = time.time()
print("画图形: %.0f ms" % ((t1 - t0) * 1000))

t0 = time.time()
scr.flush()
t1 = time.time()
print("★ 全屏推送到显存: %.0f ms" % ((t1 - t0) * 1000))

t0 = time.time()
for _ in range(5):
    scr.flush()
t1 = time.time()
print("★ 连续5帧平均: %.0f ms/帧  (约 %.1f FPS)" % ((t1-t0)*1000/5, 5/(t1-t0)))

print("")
print(">>> 现在请在屏幕上点几下 (15秒) <<<")
t = Touch()
end = time.time() + 15
while time.time() < end:
    ev = t.poll()
    if ev:
        print("  事件:", ev)
        x, y = ev[1], ev[2]
        scr.rrect([x-30, y-30, x+30, y+30], 30, fill=(255, 80, 80))
        scr.flush((x-32, y-32, x+32, y+32))
    time.sleep(0.02)
print("测试结束")
