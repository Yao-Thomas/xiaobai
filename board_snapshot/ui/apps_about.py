#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_about.py —— 关于本项目 (紧凑版, 600px 内放得下)"""
import time

SECTIONS = [
    ("硬件", [
        "正点原子 领航者 ZYNQ7020 (ATK-DF7010/7020P)",
        "Xilinx Zynq-7020  双核 Cortex-A9 @667MHz + 1GB DDR3",
        "7 寸 RGB LCD 1024x600 + GT911 电容触摸",
        "AIC8800D80  USB WiFi6 无线网卡",
    ]),
    ("系统", [
        "Ubuntu 20.04.5 LTS armhf (自建根文件系统)",
        "Linux 5.4.0-xilinx-v2020.2 (正点原子板级适配)",
        "支持 apt 安装任意软件",
    ]),
    ("自己写的", [
        "WiFi6 驱动(交叉编译) · 触摸图形库 · 本桌面 · 扫雷",
    ]),
    ("下一步", [
        "ESP32-S3 / GPS / OLED 模块接入",
        "FPGA 示波器  ·  FPGA 简易 GPU",
    ]),
]

def draw(scr):
    scr.clear((19, 19, 19))
    scr.rect([0, 0, scr.w, 56], fill=(40, 30, 70))
    scr.rect([0, 54, scr.w, 58], fill=(150, 110, 220))
    scr.rrect([10, 7, 126, 49], 9, fill=(70, 60, 110))
    scr.text((68, 28), "< 返回", 20, (255, 255, 255), cn=True, anchor="mm")
    scr.text((146, 28), "关于", 24, (235, 235, 235), cn=True, anchor="lm")

    y = 70
    scr.text((60, y), "Zynq-7020 板载小电脑", 30, (255, 220, 120), cn=True, bold=True)
    y += 46
    for title, items in SECTIONS:
        scr.rrect([60, y, scr.w - 60, y + 30], 7, fill=(58, 44, 96))
        scr.text((74, y + 15), title, 19, (205, 175, 255), cn=True, anchor="lm")
        y += 36
        for it in items:
            scr.text((82, y), "· " + it, 18, (217, 217, 217), cn=True)
            y += 26
        y += 6
    scr.text((scr.w // 2, scr.h - 16), "点“返回”回桌面", 17, (140, 130, 180),
             cn=True, anchor="mm")

def run(scr, touch):
    draw(scr)
    scr.flush()
    while True:
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if 0 <= x <= 140 and 0 <= y <= 58:
                return
        time.sleep(0.05)
