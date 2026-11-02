#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""warm_wall_thumbs.py —— 预生成壁纸缩略图缓存"""
import sys, os, time
sys.path.insert(0, "/home/zynq/ui")
import apps_wallpaper as W

fs = W.list_wallpapers()
print("  找到 %d 张图片" % len(fs))
t0 = time.time()
n = W.warm_cache(fs)
dt = time.time() - t0
print("  预生成 %d 张缩略图, 用时 %.1f 秒 (平均 %.0f ms/张)" %
      (n, dt, dt * 1000.0 / max(1, n)))
if os.path.isdir(W.THUMB_CACHE):
    print("  缓存目录 %s -> %d 个文件" %
          (W.THUMB_CACHE, len(os.listdir(W.THUMB_CACHE))))
# 测一下读缓存的速度
t0 = time.time()
for f in fs:
    W.make_thumb(f)
print("  读缓存全部 %d 张: %.2f 秒" % (len(fs), time.time() - t0))
