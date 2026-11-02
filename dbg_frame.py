#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_frame.py —— 同一帧, 分别在"有/无 跳过区"下渲染, 数空列比例"""
import ctypes
import sys

sys.path.insert(0, "/home/zynq/ui")
import fbui
import apps_mc as A

scr = fbui.Screen()
touch = fbui.Touch()
mc = A.MC(scr, touch)
W, H = A.W, A.H
buf = (ctypes.c_ubyte * (W * H * 3))()
p = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))

print("skip 参数: top=%d hole=(%d,%d)-(%d,%d)" % (
    A.MC.BAR_H, A.MC.CTRL_X, A.MC.MATBAR_XY[1], A.W, A.H))
print("相机: x=%.1f y=%.1f z=%.1f yaw=%.2f pitch=%.2f maxd=%d"
      % (mc.x, mc.y, mc.z, mc.yaw, mc.pitch, A.MAXD))


def measure(tag):
    mc.lib.mc_render(p, mc.x, mc.y, mc.z, mc.yaw, mc.pitch, A.MAXD)
    b = bytes(buf)
    i0 = (120 * W + 1000) * 3
    sky = (b[i0], b[i0 + 1], b[i0 + 2])
    blank = 0
    tot = 0
    firstblank = -1
    for x in range(0, W, 8):
        tot += 1
        has = False
        for y in range(150, 600, 6):
            i = (y * W + x) * 3
            if abs(b[i] - sky[0]) + abs(b[i + 1] - sky[1]) + abs(b[i + 2] - sky[2]) > 40:
                has = True
                break
        if not has:
            blank += 1
            if firstblank < 0:
                firstblank = x
    print("  %-14s 空列 %5.0f%%  (采样 %d 列, 第一个空列 x=%d)  天空色=%s"
          % (tag, blank * 100.0 / tot, tot, firstblank, sky))


measure("有跳过区")
mc.lib.mc_set_skip(0, 0, 0, 0, 0)
measure("无跳过区")
mc.lib.mc_set_skip(A.MC.BAR_H, A.MC.CTRL_X, A.MC.MATBAR_XY[1], A.W, A.H)

# 再单独试: 只留 SKIP_TOP, 洞取零
mc.lib.mc_set_skip(A.MC.BAR_H, 0, 0, 0, 0)
measure("只跳顶部")
