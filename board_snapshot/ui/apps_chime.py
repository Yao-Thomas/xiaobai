#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_chime.py —— 提示音选择界面

点一下试听一个，挑中哪个按「设为默认」。
就是为了让人**一个一个试**，不用我在这儿猜哪个好听。

* 左边是名字，右边点一下就播
* 顶部：停止 / 音量- / 音量+ / 设为默认 / 全部生成
* 播放走板载音频服务（:8767），HTTP 在后台线程，界面不卡

★ 为什么要有这个：之前声学自证我用了原始正弦/蜂鸣器，太刺耳；
  正确做法是让人自己挑一个正常好听的提示音。
"""
import os
import json
import time
import queue
import threading
import urllib.request

from fbui import header, back_hit, btn, hit

AUDIO_URL = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")
OUTDIR = "/home/zynq/Music/提示音"
DEFAULT = "/home/zynq/Music/提示音.wav"

LIST_RECT = [36, 108, 988, 500]
STATUS_RECT = [36, 508, 988, 546]
ROW_H = 44


def _post(url, obj, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wav_secs(p):
    try:
        import wave
        with wave.open(p, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


class ChimePicker(object):
    def __init__(self):
        self.q = queue.Queue()
        self.busy = ""
        self.sel = 0
        self.status = "点一下名字就试听；挑好了按「设为默认」"
        self.styles = []
        self.playing = ""
        self.volume = 20
        self.generate()

    # ---- 生成所有提示音 ----
    def generate(self):
        try:
            import chime
        except Exception as e:
            self.status = "无法 import chime: %s" % e
            return
        os.makedirs(OUTDIR, exist_ok=True)
        for key in chime.STYLES:
            p = os.path.join(OUTDIR, "%s.wav" % key)
            if not os.path.exists(p):
                s = chime.make_chime(key)
                chime.write_wav(s, p)
        self.styles = [(k, chime.STYLE_NAMES.get(k, k),
                        os.path.join(OUTDIR, "%s.wav" % k))
                       for k in chime.STYLES]
        self.status = "已生成 %d 个提示音到 %s" % (len(self.styles), OUTDIR)

    # ---- 后台 ----
    def _bg(self, name, fn):
        if self.busy:
            return
        self.busy = name

        def wrap():
            try:
                self.q.put((name, fn()))
            except Exception as e:
                self.q.put((name, "错误: %s: %s" % (type(e).__name__, e)))
        threading.Thread(target=wrap, daemon=True).start()

    def play(self, i):
        if not (0 <= i < len(self.styles)):
            return
        self.sel = i
        key, nm, path = self.styles[i]

        def fn():
            self.playing = key
            _post(AUDIO_URL + "/volume", {"v": self.volume})
            _post(AUDIO_URL + "/play", {"file": path})
            self.playing = ""
            return "试听: %s (%s, %.2fs)" % (nm, key, wav_secs(path))
        self._bg("play", fn)

    def stop(self):
        def fn():
            _post(AUDIO_URL + "/stop", {})
            self.playing = ""
            return "已停止"
        self._bg("stop", fn)

    def set_default(self):
        key, nm, path = self.styles[self.sel]

        def fn():
            import shutil
            shutil.copy(path, DEFAULT)
            return "★ 已把「%s」设为默认提示音 -> %s" % (nm, DEFAULT)
        self._bg("set", fn)

    def vol(self, d):
        self.volume = max(0, min(33, self.volume + d))
        self.status = "音量 %d（0..33）" % self.volume
        try:
            _post(AUDIO_URL + "/volume", {"v": self.volume}, timeout=8)
        except Exception:
            pass

    def pump(self):
        while True:
            try:
                name, res = self.q.get_nowait()
            except queue.Empty:
                return
            self.busy = ""
            self.status = str(res)

    # ---- 绘制 ----
    def buttons(self, scr):
        b = []
        x = 36
        for name, act in (("停止", "stop"),
                          ("音量 -", ("vol", -3)),
                          ("音量 +", ("vol", 3)),
                          ("设为默认", "set"),
                          ("重新生成", "gen")):
            w = scr.tw(name, 17, cn=True) + 26
            b.append((name, act, [x, 66, x + w, 100]))
            x += w + 8
        return b

    def draw(self, scr, btns):
        scr.clear((16, 16, 16))
        header(scr, "提示音选择")
        for name, act, r in btns:
            key = act[0] if isinstance(act, tuple) else act
            on = (self.busy == key or self.busy == act)
            btn(scr, r, name, fill=(150, 90, 40) if on else (52, 70, 120),
                size=17, cn=True, radius=8)
        scr.text((1000, 83), "音量 %d" % self.volume, 16, (200, 220, 255),
                 anchor="rm", cn=True)

        scr.rrect(LIST_RECT, 8, fill=(10, 10, 10), outline=(50, 70, 110))
        y = LIST_RECT[1] + 8
        for i, (key, nm, path) in enumerate(self.styles):
            r = [LIST_RECT[0] + 6, y, LIST_RECT[2] - 6, y + ROW_H - 5]
            cur = (i == self.sel)
            if cur:
                scr.rrect(r, 6, fill=(38, 60, 110), outline=(90, 140, 230))
            mark = "▶ " if self.playing == key else "  "
            scr.text((r[0] + 14, y + ROW_H // 2 - 3), mark + nm, 20,
                     (255, 240, 200) if cur else (205, 220, 245),
                     anchor="lm", cn=True)
            scr.text((r[0] + 230, y + ROW_H // 2 - 3), key, 16, (140, 165, 205),
                     anchor="lm", mono=True)
            scr.text((r[2] - 14, y + ROW_H // 2 - 3), "%.2fs" % wav_secs(path),
                     16, (140, 170, 210), anchor="rm")
            y += ROW_H

        scr.rrect(STATUS_RECT, 8, fill=(26, 26, 26), outline=(70, 100, 160))
        scr.text((STATUS_RECT[0] + 12, (STATUS_RECT[1] + STATUS_RECT[3]) // 2),
                 self.status[-92:], 17, (232, 232, 232), anchor="lm", cn=True)
        scr.text((1000, 570), "默认提示音会存成 %s" % DEFAULT, 14,
                 (140, 160, 195), anchor="rm", cn=True)


def run(scr, touch):
    p = ChimePicker()
    while True:
        p.pump()
        btns = p.buttons(scr)
        p.draw(scr, btns)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            done = False
            for name, act, r in btns:
                if hit(r, x, y):
                    if act == "stop":
                        p.stop()
                    elif act == "set":
                        p.set_default()
                    elif act == "gen":
                        p.generate()
                    elif isinstance(act, tuple) and act[0] == "vol":
                        p.vol(act[1])
                    done = True
                    break
            if done:
                continue
            if hit(LIST_RECT, x, y):
                i = (y - LIST_RECT[1] - 8) // ROW_H
                if 0 <= i < len(p.styles):
                    p.play(i)
        time.sleep(0.03)
