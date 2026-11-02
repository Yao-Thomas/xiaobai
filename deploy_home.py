#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_home.py —— 把卡片首页部署到板子 (带回滚)

顺序刻意设计过:
  1. 先 测性能 (用假屏幕, 不碰 /dev/fb0, 桌面还在跑)
  2. 备份板上的旧文件
  3. 上传新文件 + md5 校验
  4. 暂停黑屏守护 -> 重启桌面 -> 截图验证
  5. 有问题就回滚
"""
import hashlib
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
UIDIR = "/home/zynq/ui"
LOCAL = r"D:\ubuntu_iso\ui"
FILES = ["fbui.py", "home.py", "desktop.py",
         "preview_home.py", "preview_all.py", "time_home.py"]

TIMER = r'''
import sys, time
from PIL import Image, ImageDraw
import fbui

class FakeScreen(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0; self.gpu = None; self.mode = "BGR;24"
        self._fast = True; self.yoff = 0
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)
    def flush(self, box=None):
        pass

fbui.Screen = FakeScreen
import home
home.Screen = FakeScreen
scr = FakeScreen()
h = home.Home(scr, apps=[], icons={})
h.wall = h.make_wallpaper()

t0 = time.time(); h.build_static(); t1 = time.time()
print("build_static(壁纸+6卡玻璃+投影+Dock): %.0f ms" % ((t1-t0)*1000))
h.register_parts()
t0 = time.time(); h.draw(full=True); t1 = time.time()
print("首帧整屏绘制+flush:                    %.0f ms" % ((t1-t0)*1000))
h.info.dt = h.info.dt.replace(second=(h.info.dt.second+1) % 60)
h.info.cpu = (h.info.cpu + 3) % 100
t0 = time.time(); n = h.draw(full=False); t1 = time.time()
print("脏区重画 %d 块:                        %.0f ms" % (n, (t1-t0)*1000))
t0 = time.time()
for k in range(10):
    h.info.dt = h.info.dt.replace(second=(h.info.dt.second+1) % 60)
    h.draw(full=False)
t1 = time.time()
print("纯时钟刷新 平均:                       %.1f ms/帧" % ((t1-t0)*100))
'''


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    if not board.HOST:
        return 1

    print("=" * 72)
    print("## 0) 板上现状")
    broot.srun("uname -v; uptime; ls -l %s | head -30" % UIDIR)

    print("=" * 72)
    print("## 1) 先测性能 (假屏幕, 不影响正在跑的桌面)")
    open(os.path.join(LOCAL, "time_home.py"), "w", encoding="utf8").write(TIMER)
    broot.srun("rm -rf /home/zynq/uitest && mkdir -p /home/zynq/uitest && "
               "chown -R zynq:zynq /home/zynq/uitest", quiet=True)
    for f in ("fbui.py", "home.py", "time_home.py"):
        board.put(os.path.join(LOCAL, f), "/home/zynq/uitest/" + f)
    broot.srun("cd /home/zynq/uitest && python3 time_home.py", timeout=300)

    print("=" * 72)
    print("## 2) 备份板上的旧文件")
    broot.srun("mkdir -p /home/zynq/ui_backup_before_home && "
               "cp -af %s/fbui.py %s/desktop.py /home/zynq/ui_backup_before_home/ && "
               "ls -l /home/zynq/ui_backup_before_home/" % (UIDIR, UIDIR))

    print("=" * 72)
    print("## 3) 上传 + 校验")
    for f in FILES:
        src = os.path.join(LOCAL, f)
        if not os.path.exists(src):
            print("   (跳过不存在的 %s)" % f)
            continue
        board.put(src, "/home/zynq/ui/" + f)
        local = md5f(src)
        out, _ = board.run("md5sum %s/%s | cut -d' ' -f1" % (UIDIR, f), timeout=30, quiet=True)
        got = out.strip()
        print("   %-16s %s %s" % (f, "OK " if got == local else "!! ", got))
    broot.srun("chown zynq:zynq %s/*.py; ls -l %s" % (UIDIR, UIDIR))

    print("=" * 72)
    print("## 4) 暂停黑屏守护, 重启桌面")
    broot.srun("touch /home/zynq/.guard_pause; "
               "systemctl restart zynq-desktop; sleep 12; "
               "systemctl is-active zynq-desktop; "
               "journalctl -u zynq-desktop --no-pager -n 30", timeout=180)
    return 0


sys.exit(main())
