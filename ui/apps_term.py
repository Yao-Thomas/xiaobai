#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_term.py —— 命令面板 (屏上键盘 + 常用命令快捷按钮)"""
import os, time, subprocess
from fbui import header, back_hit, btn, hit, MiniKeyboard

PRESETS = [
    ("ls", "ls -lh ~"),
    ("df", "df -h /"),
    ("net", "ip -br addr"),
    ("ps", "ps aux --sort=-%cpu | head -8"),
    ("mem", "free -m"),
    ("温度", "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null || echo N/A"),
    ("dmesg", "dmesg | tail -12"),
    ("清除", None),
]

OUT_RECT = [52, 116, 972, 336]
IN_RECT = [52, 344, 972, 386]

class Term:
    def __init__(self):
        self.lines = ["Zynq 命令面板 —— 点下面按钮或打字后按回车"]
        self.cur = ""
        self.kb = MiniKeyboard(y0=396, key_w=86, key_h=44, gap=5)

    def out(self, s):
        for ln in str(s).splitlines():
            self.lines.append(ln[:110])
        self.lines = self.lines[-200:]

    def run_cmd(self, cmd):
        self.out("$ " + cmd)
        if cmd.strip() in ("clear", "清除"):
            self.lines = []
            return
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=25)
            if r.stdout:
                self.out(r.stdout.decode(errors="replace"))
            if r.stderr:
                self.out(r.stderr.decode(errors="replace"))
        except subprocess.TimeoutExpired:
            self.out("[命令超时]")
        except Exception as ex:
            self.out("[错误] %s" % ex)

    def draw(self, scr):
        scr.clear((12, 14, 24))
        header(scr, "命令面板")
        # 快捷按钮
        x = 52
        for name, cmd in PRESETS:
            w = scr.tw(name, 17, cn=True) + 26
            btn(scr, [x, 70, x + w, 106], name, fill=(52, 70, 110) if cmd else (130, 60, 60),
                size=17, cn=True, radius=8)
            x += w + 7
        # 输出区
        scr.rrect(OUT_RECT, 8, fill=(6, 8, 16), outline=(50, 70, 110))
        y = OUT_RECT[1] + 8
        maxl = (OUT_RECT[3] - OUT_RECT[1] - 12) // 22
        for ln in self.lines[-maxl:]:
            scr.text((OUT_RECT[0] + 10, y), ln, 17, (180, 230, 190), mono=True)
            y += 22
        # 输入行
        scr.rrect(IN_RECT, 8, fill=(20, 26, 44), outline=(70, 100, 160))
        scr.text((IN_RECT[0] + 10, (IN_RECT[1] + IN_RECT[3]) // 2),
                 "$ " + self.cur[-70:] + "_", 20, (230, 240, 255), anchor="lm", mono=True)
        # 键盘
        self.kb.draw(scr)


def run(scr, touch):
    t = Term()
    while True:
        t.draw(scr)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            # 快捷命令
            x2 = 52
            hitp = False
            for name, cmd in PRESETS:
                w = scr.tw(name, 17, cn=True) + 26
                if hit([x2, 70, x2 + w, 106], x, y):
                    if cmd is None:
                        t.lines = []
                    else:
                        t.run_cmd(cmd)
                    hitp = True
                    break
                x2 += w + 7
            if hitp:
                continue
            # 键盘
            k = t.kb.press(x, y)
            if k is not None:
                if k == "<BS>":
                    t.cur = t.cur[:-1]
                elif k == "<ENTER>":
                    if t.cur.strip():
                        t.run_cmd(t.cur)
                        t.cur = ""
                else:
                    t.cur += k
                print("终端输入:", repr(t.cur))
        time.sleep(0.025)
