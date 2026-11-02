#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reset_pages.py —— 把桌面页面布局重置成 1 页"""
import json

P = "/home/zynq/.desktop_pages"
pages = [["扫雷", "计算器", "画板", "文件", "图片", "命令面板",
          "GPU 加速", "系统信息", "WiFi", "壁纸", "关于", None]]
with open(P, "w") as f:
    json.dump(pages, f, ensure_ascii=False)
print("已重置为 1 页:")
print(" ", json.dumps(pages, ensure_ascii=False))
