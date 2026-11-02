#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_skip.py —— 打印 MC 传给渲染器的"跳过区"参数"""
import sys
sys.path.insert(0, "/home/zynq/ui")
import apps_mc as a

print("W,H        =", a.W, a.H)
print("RW,RH      =", a.RW, a.RH)
print("FOCAL      =", a.FOCAL)
print("MAXD,REACH =", a.MAXD, a.REACH)
print("BAR_H      =", a.MC.BAR_H)
print("CTRL_X/Y   =", a.MC.CTRL_X, a.MC.CTRL_Y)
print("MATBAR_XY  =", a.MC.MATBAR_XY)
print("MATBAR_WH  =", a.MC.MATBAR_WH)
print("INFO_XY/WH =", a.MC.INFO_XY, a.MC.INFO_WH)
print("MSG_WH     =", a.MC.MSG_WH)
print()
print("mc_set_skip 实际参数 = (%d, %d, %d, %d, %d)" % (
    a.MC.BAR_H, a.MC.CTRL_X, a.MC.MATBAR_XY[1], a.W, a.H))
