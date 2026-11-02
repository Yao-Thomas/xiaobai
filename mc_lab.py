#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mc_lab.py —— 调试板子的实验台

用法:
    python mc_lab.py shot out.png          抓一张板子屏幕
    python mc_lab.py idle N out_prefix     连续抓 N 张, 报告相邻帧差异(量化"颤抖")
    python mc_lab.py tap X Y               注入一次点击
    python mc_lab.py drag x1,y1;x2,y2      注入一次拖拽
    python mc_lab.py cmd "uname -a"        在板子上跑命令
    python mc_lab.py put 本地 远端          传文件
    python mc_lab.py get 远端 本地          取文件
"""
import os
import sys
import time

import paramiko
from PIL import Image, ImageChops

HOST = os.environ.get("BOARD_IP", "192.168.10.18")
USER, PASS = "zynq", "123456"
W, H, STRIDE = 1024, 600, 3072


class Board:
    def __init__(self, host=HOST):
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(host, username=USER, password=PASS, timeout=20,
                       look_for_keys=False, allow_agent=False)
        self.sftp = self.c.open_sftp()

    def run(self, cmd, timeout=60):
        i, o, e = self.c.exec_command(cmd, timeout=timeout)
        try:
            o.channel.settimeout(timeout)
        except Exception:
            pass
        out = ""
        err = ""
        try:
            out = o.read().decode("utf-8", "replace")
        except Exception as ex:
            out = "[read timeout: %s]" % ex
        try:
            err = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return out + err

    def sudo(self, cmd, timeout=60):
        return self.run("echo 123456 | sudo -S bash -c %s" % shq(cmd), timeout)

    def put(self, local, remote):
        self.sftp.put(local, remote)

    def get(self, remote, local):
        self.sftp.get(remote, local)

    def pan_rows(self):
        """当前【正在显示】的是第几页(行偏移)。

        ★ 双缓冲之后, 显示的可能不是第 0 页。`dd if=/dev/fb0 bs=3072 count=600`
          永远只读第 0 页 —— 不按 pan 去读就会截到"没在显示的那一页",
          看着右半边一片空白, 像是渲染坏了。
        """
        try:
            t = self.run("cat /sys/class/graphics/fb0/pan", 20).strip()
            if "," in t:
                return int(t.split(",")[1])
        except Exception:
            pass
        return 0

    def shot(self, out="shot.png", freeze=False):
        # ★ freeze: 截图前先 SIGSTOP 掉渲染进程。
        #   C 是逐列左->右渲染(先铺天再盖地形), dd 是逐行读 1.8MB,
        #   不冻结的话很容易抓到"左边有地形、右边还是天"的半成品帧。
        if freeze:
            # ★ 用【帧边界暂停文件】而不是 SIGSTOP。
            #   SIGSTOP 会在下一个调度点生效, 而 C 渲染是一次很长的调用,
            #   于是经常停在一帧中间, 截出来是"左边有地形右边还是天"的
            #   半成品。程序自己在帧开头检查这个文件就一定是完整帧。
            self.sudo("touch /tmp/mc_pause /tmp/fight_pause")
            time.sleep(0.6)
            self.sudo("touch /tmp/mc_pause /tmp/fight_pause")
            time.sleep(0.4)
        r = self.sudo("dd if=/dev/fb0 of=/tmp/_shot.raw bs=%d skip=%d count=%d "
                      "2>/dev/null; chmod 644 /tmp/_shot.raw"
                      % (STRIDE, self.pan_rows(), H))
        tmp = out + ".raw"
        self.sftp.get("/tmp/_shot.raw", tmp)
        self.sudo("rm -f /tmp/_shot.raw")
        if freeze:
            self.sudo("rm -f /tmp/mc_pause /tmp/fight_pause")
        raw = open(tmp, "rb").read()
        os.remove(tmp)
        if len(raw) < STRIDE * H:
            raw = raw + b"\x00" * (STRIDE * H - len(raw))
        raw = raw[:STRIDE * H]
        im = Image.frombytes("RGB", (W, H), bytes(
            b for y in range(H)
            for i in range(y * STRIDE, y * STRIDE + W * 3, 3)
            for b in (raw[i + 2], raw[i + 1], raw[i])))
        im.save(out)
        return im

    def tap(self, x, y):
        self.run('echo "%d,%d" > /tmp/ui_tap' % (x, y))

    def drag(self, pts):
        s = "drag:" + ";".join("%d,%d" % p for p in pts)
        self.run('echo "%s" > /tmp/ui_tap' % s)

    def ev(self, kind, x, y):
        self.run('echo "%s:%d,%d" > /tmp/ui_tap' % (kind, x, y))

    def close(self):
        try:
            self.sftp.close()
        except Exception:
            pass
        self.c.close()


def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def diffstat(imgs):
    """报告相邻帧的差异像素数与最大差异 —— 静置时应该全 0"""
    print("%-6s %-14s %-14s %s" % ("帧", "变化像素数", "占比", "最大通道差"))
    for i in range(1, len(imgs)):
        d = ImageChops.difference(imgs[i - 1], imgs[i])
        px = d.convert("L").point(lambda v: 255 if v > 4 else 0)
        n = sum(px.histogram()[255:])
        mx = max(d.getextrema(), key=lambda t: t[1])[1]
        print("%-6d %-14d %-14s %d" % (i, n, "%.2f%%" % (n * 100.0 / (W * H)), mx))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    a = sys.argv[1]
    b = Board()
    try:
        if a == "shot":
            b.shot(sys.argv[2] if len(sys.argv) > 2 else "shot.png")
            print("OK")
        elif a == "idle":
            n = int(sys.argv[2])
            pre = sys.argv[3] if len(sys.argv) > 3 else "idle"
            imgs = []
            for i in range(n):
                imgs.append(b.shot("%s_%d.png" % (pre, i)))
                time.sleep(0.7)
            diffstat(imgs)
        elif a == "tap":
            b.tap(int(sys.argv[2]), int(sys.argv[3]))
        elif a == "drag":
            pts = [tuple(int(v) for v in p.split(",")) for p in sys.argv[2].split(";")]
            b.drag(pts)
        elif a == "cmd":
            print(b.run(sys.argv[2]))
        elif a == "sudo":
            print(b.sudo(sys.argv[2]))
        elif a == "put":
            b.put(sys.argv[2], sys.argv[3])
            print("OK")
        elif a == "get":
            b.get(sys.argv[2], sys.argv[3])
            print("OK")
        else:
            print(__doc__)
    finally:
        b.close()


if __name__ == "__main__":
    main()
