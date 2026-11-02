#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""upload_wallpapers.py —— 把电脑上的壁纸批量传到板子

用法: python upload_wallpapers.py
会自动找板子 IP (board.py 里的逻辑)
"""
import os, sys, glob

sys.path.insert(0, r"D:\ubuntu_iso")
import importlib.util
spec = importlib.util.spec_from_file_location("bd", r"D:\ubuntu_iso\board.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)
print("板子 IP:", bd.HOST)

SRC = r"C:\Users\姚恩奇\Pictures\壁纸"
DST = "/home/zynq/Pictures/wallpapers"
EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif")

files = []
for f in sorted(glob.glob(os.path.join(SRC, "*"))):
    if f.lower().endswith(EXTS) and os.path.isfile(f):
        files.append(f)
print("找到 %d 张图片" % len(files))

# 建立 ssh/sftp 连接
c = bd.conn()
sftp = c.open_sftp()
# 确保目标目录存在
try:
    sftp.stat(DST)
except IOError:
    sftp.mkdir(DST)
    print("已创建目录", DST)

ok = 0
for i, f in enumerate(files, 1):
    ext = os.path.splitext(f)[1].lower()
    name = "壁纸%02d%s" % (i, ext)
    remote = DST + "/" + name
    local_sz = os.path.getsize(f)
    try:
        sftp.put(f, remote)
        print("  [%2d/%d] %s  (%.0f KB) -> %s" %
              (i, len(files), os.path.basename(f), local_sz / 1024.0, name))
        ok += 1
    except Exception as ex:
        print("  [%2d/%d] ❌ 失败: %s  (%s)" % (i, len(files), os.path.basename(f), ex))

sftp.close()
c.close()
print("\n✅ 成功上传 %d / %d 张" % (ok, len(files)))
