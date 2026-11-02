#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_music.py —— 板载 WAV 播放器 + 录音器

* 列出 /home/zynq/Music 下的 .wav，点一下就用板载喇叭放出来
* 「录音」按钮直接开麦克风录一段，存成 WAV 到 /home/zynq/Music
* 状态写到 /tmp/zynq_music.json，首页音乐卡读它显示"正在播放"

【2026-09-29 新增】「删除」按钮
    - 两次点击确认（第一次提示，第二次才真删），防止误删
    - 正在播放的文件不允许删
    - 任意格式 WAV 的播放兼容由音频服务负责（会转成 44100/2ch）

★ 所有 HTTP / 录音 / 删文件都在后台线程里跑，主循环绝不阻塞。
"""
import os
import io
import json
import time
import wave
import queue
import struct
import threading
import urllib.request

from fbui import header, back_hit, btn, hit

AUDIO_URL = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")
MUSIC_DIR = "/home/zynq/Music"
STATE = "/tmp/zynq_music.json"

LIST_RECT = [36, 108, 988, 492]
STATUS_RECT = [36, 500, 988, 540]
ROW_H = 38
CONFIRM_SECS = 5.0          # 两次点击的确认窗口


def _post(url, obj, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_raw(url, obj, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def wav_secs(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def scan():
    try:
        os.makedirs(MUSIC_DIR, exist_ok=True)
    except Exception:
        pass
    out = []
    for fn in sorted(os.listdir(MUSIC_DIR)):
        if fn.lower().endswith(".wav"):
            p = os.path.join(MUSIC_DIR, fn)
            try:
                out.append((fn, p, os.path.getsize(p), wav_secs(p)))
            except Exception:
                pass
    out.sort(key=lambda x: -os.path.getmtime(x[1]))
    return out


def write_state(title, playing, pos=0, ln=0):
    try:
        with open(STATE, "w") as f:
            json.dump({"title": title, "playing": playing,
                       "pos": pos, "len": ln, "t": time.time()}, f)
    except Exception:
        pass


class Music(object):
    def __init__(self):
        self.files = scan()
        self.sel = 0
        self.q = queue.Queue()
        self.busy = ""
        self.status = ("找到 %d 个 WAV。点文件名播放，「删除」删选中项。"
                       % len(self.files))
        self.playing = ""
        self.rec_secs = 5.0
        self.pending_del = None      # 待确认删除的路径
        self.pending_t = 0.0

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

    def refresh(self):
        self.files = scan()
        if self.sel >= len(self.files):
            self.sel = max(0, len(self.files) - 1)
        self.status = "刷新完成，%d 个 WAV" % len(self.files)

    def play(self, i):
        if not (0 <= i < len(self.files)):
            return
        self.sel = i
        name, path, size, secs = self.files[i]

        def fn():
            self.playing = name
            write_state(name, True, 0, int(secs))
            r = _post(AUDIO_URL + "/play", {"file": path})
            write_state(name, False, int(secs), int(secs))
            self.playing = ""
            return "放完 %s（%.1f 秒）" % (name, secs)
        self._bg("play", fn)

    def delete(self):
        """删除当前选中项。第一次点击只提示，窗口内再点一次才真删。"""
        i = self.sel
        if not (0 <= i < len(self.files)):
            self.status = "没有选中文件"
            return
        name, path, size, secs = self.files[i]

        now = time.time()
        if self.pending_del == path and (now - self.pending_t) < CONFIRM_SECS:
            def fn():
                if self.playing == name:
                    self.pending_del = None
                    raise RuntimeError("正在播放，先点「停止」再删")
                os.remove(path)
                self.pending_del = None
                self.files = scan()
                if self.sel >= len(self.files):
                    self.sel = max(0, len(self.files) - 1)
                return "已删除 %s，释放 %.0f KB（剩 %d 个）" % (
                    name, size / 1024.0, len(self.files))
            self._bg("delete", fn)
        else:
            self.pending_del = path
            self.pending_t = now
            self.status = "⚠ 再点一次「删除」确认删除: %s（%.0f KB）" % (
                name, size / 1024.0)

    def record(self, secs):
        self.rec_secs = secs

        def fn():
            wav = _post_raw(AUDIO_URL + "/record",
                            {"secs": secs, "rate": 16000, "mono": True},
                            timeout=secs + 240)
            os.makedirs(MUSIC_DIR, exist_ok=True)
            name = "录音_%s.wav" % time.strftime("%m%d_%H%M%S")
            path = os.path.join(MUSIC_DIR, name)
            with open(path, "wb") as f:
                f.write(wav)
            self.files = scan()
            self.sel = 0
            return "录好了: %s (%d 字节) -> %s" % (name, len(wav), path)
        self._bg("record", fn)

    def stop(self):
        def fn():
            _post(AUDIO_URL + "/stop", {}, timeout=15)
            write_state("", False)
            self.playing = ""
            return "已停"
        self._bg("stop", fn)

    def selftest(self):
        def fn():
            d = _post(AUDIO_URL + "/selftest", {"freq": 990.53, "secs": 1.2},
                      timeout=240)
            return "自检: %s   @%.0fHz 静音%.0f -> 放音%.0f (%.1f dB)" % (
                d.get("verdict"), d.get("freq", 990),
                d.get("goe_quiet", 0), d.get("goe_tone", 0),
                d.get("ratio_db", 0))
        self._bg("selftest", fn)

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
        for name, act in (("录音 3 秒", ("rec", 3.0)),
                          ("录音 8 秒", ("rec", 8.0)),
                          ("停止", "stop"),
                          ("刷新", "refresh"),
                          ("删除", "delete"),
                          ("自检", "selftest")):
            w = scr.tw(name, 17, cn=True) + 26
            b.append((name, act, [x, 66, x + w, 100]))
            x += w + 8
        return b

    def draw(self, scr, btns):
        scr.clear((14, 14, 14))
        header(scr, "音乐 / 录音机")
        for name, act, r in btns:
            on = (self.busy == (act[0] if isinstance(act, tuple) else act))
            # 「删除」按钮在有待确认项时变红，提示"再点一次"
            danger = (act == "delete" and self.pending_del)
            fill = (150, 90, 40) if on else ((170, 50, 50) if danger
                                             else (52, 70, 120))
            btn(scr, r, name, fill=fill, size=17, cn=True, radius=8)
        if self.busy:
            scr.text((1000, 83), "工作中:" + self.busy, 16, (250, 200, 120),
                     anchor="rm", cn=True)

        scr.rrect(LIST_RECT, 8, fill=(8, 8, 8), outline=(50, 70, 110))
        y = LIST_RECT[1] + 8
        if not self.files:
            scr.text((LIST_RECT[0] + 14, y + 10),
                     "还没有音频。把 .wav 放进 %s，或点「录音 3 秒」。" % MUSIC_DIR,
                     18, (170, 190, 220), cn=True)
        for i, (name, path, size, secs) in enumerate(self.files):
            if y + ROW_H > LIST_RECT[3] - 4:
                scr.text((LIST_RECT[0] + 14, y + 4), "... 还有 %d 个"
                         % (len(self.files) - i), 16, (150, 170, 200), cn=True)
                break
            r = [LIST_RECT[0] + 6, y, LIST_RECT[2] - 6, y + ROW_H - 4]
            cur = (i == self.sel)
            pend = (path == self.pending_del)
            if pend:
                scr.rrect(r, 6, fill=(90, 24, 30), outline=(235, 90, 90))
            elif cur:
                scr.rrect(r, 6, fill=(38, 60, 110), outline=(90, 140, 230))
            col = (255, 240, 200) if (cur and not pend) else (200, 215, 240)
            if pend:
                col = (255, 190, 190)
            mark = "▶ " if (self.playing and self.playing == name) else "  "
            scr.text((r[0] + 12, y + ROW_H // 2 - 2), mark + name, 18, col,
                     anchor="lm", cn=True)
            scr.text((r[2] - 12, y + ROW_H // 2 - 2),
                     "%.1fs  %.0fKB" % (secs, size / 1024.0), 16,
                     (140, 170, 210), anchor="rm")
            y += ROW_H

        scr.rrect(STATUS_RECT, 8, fill=(26, 26, 26), outline=(70, 100, 160))
        scr.text((STATUS_RECT[0] + 12, (STATUS_RECT[1] + STATUS_RECT[3]) // 2),
                 self.status[-96:], 17, (232, 232, 232), anchor="lm", cn=True)


def run(scr, touch):
    m = Music()
    while True:
        m.pump()
        btns = m.buttons(scr)
        m.draw(scr, btns)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            done = False
            for name, act, r in btns:
                if hit(r, x, y):
                    if isinstance(act, tuple) and act[0] == "rec":
                        m.record(act[1])
                    elif act == "stop":
                        m.stop()
                    elif act == "refresh":
                        m.refresh()
                    elif act == "delete":
                        m.delete()
                    elif act == "selftest":
                        m.selftest()
                    done = True
                    break
            if done:
                continue
            if hit(LIST_RECT, x, y):
                i = (y - LIST_RECT[1] - 8) // ROW_H
                if 0 <= i < len(m.files) and not m.busy:
                    # 点别的文件就取消待删确认，避免误删
                    if m.pending_del and m.pending_del != m.files[i][1]:
                        m.pending_del = None
                    print("[music] 播放:", m.files[i][0])
                    m.play(i)
        time.sleep(0.03)
