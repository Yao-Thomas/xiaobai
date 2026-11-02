#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_settings.py —— 系统设置（参考 iOS「设置」/ 华为「设置」的分组列表）

设计上照抄两家共通的那套：
  * 一页一个"分组卡片"，卡片上方一行小字标题
  * 每行 = 彩色圆角图标 + 名称 + 右侧当前值 + ">" 箭头
  * 点一行进入二级页，左上角"< 返回"
  * 二级页里是具体控件（列表 / 加减 / 按钮）

能设的东西（都是板子真实支持的）：
  声音   : 提示音（8 种，点一下试听、可设为默认）、输出音量
  语音助手: 说话音色 / 语速（espeak-ng 参数）、麦克风自检（只录音不放音）
  连接   : 无线网络（SSID/IP/信号 + 打开 WiFi 界面）
  系统   : 系统信息、后台服务（音频/Agent 状态 + 重启）、壁纸
  关于   : 关于本机

★ 所有网络/子进程都在后台线程，主循环不阻塞（这是之前"点了没反应"的教训）。
"""
import os
import json
import time
import queue
import threading
import subprocess
import urllib.request

from fbui import header, back_hit, btn, hit

AUDIO_URL = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")
AGENT_URL = os.environ.get("AGENT_SVC", "http://127.0.0.1:8765")
CHIME_DIR = "/home/zynq/Music/提示音"
CHIME_DEFAULT = "/home/zynq/Music/提示音.wav"
CONF = "/home/zynq/.xiaobai_settings.json"

# 画布尺寸
W, H = 1024, 600
HDR = 56
PAD = 30
CARD_X0, CARD_X1 = 34, W - 34
ROW_H = 48
SECT_H = 24


def _post(url, obj, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout=6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception as e:
        return "(%s)" % e


def read_conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except Exception:
        return {}


def write_conf(d):
    try:
        with open(CONF, "w") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------- 图标
BADGE_COLORS = {
    "铃": (240, 92, 92), "音": (255, 149, 0), "话": (90, 140, 245),
    "麦": (52, 199, 89), "网": (0, 122, 255), "统": (120, 120, 128),
    "服": (88, 86, 214), "壁": (255, 105, 180), "关": (142, 142, 147),
    "返": (99, 99, 102),
}


def badge(scr, x, y, s, ch, col=None):
    col = col or BADGE_COLORS.get(ch, (100, 110, 130))
    scr.rrect([x, y, x + s, y + s], int(s * 0.26), fill=col)
    scr.text((x + s // 2, y + s // 2), ch, int(s * 0.60), (255, 255, 255),
             anchor="mm", cn=True)


# ---------------------------------------------------------------- 主类
class Settings(object):
    def __init__(self):
        self.pages = ["main"]
        self.q = queue.Queue()
        self.busy = ""
        self.status = ""
        self.cfg = read_conf()
        self.volume = int(self.cfg.get("volume", 28))
        self.voice = self.cfg.get("voice", "cmn")
        self.speed = int(self.cfg.get("speed", 160))
        self.chime = self.cfg.get("chime", "apple")
        self.chime_sel = 0
        self.mic_text = ""
        self.sysinfo = {}
        self.svc = {}
        self.slider = None            # 当前页滑块的矩形（拖动时要命中它）
        self.slider_kind = None       # "volume" / "chimevol"
        self.dragging = False
        self._list_chimes()
        self._refresh_quick()

    # ---------- 滑块（可拖动）----------
    def draw_slider(self, scr, rect, value, vmax, label=None, kind="volume"):
        """画一个 iOS 风格的滑块，并把矩形存起来供拖动命中。"""
        self.slider = list(rect)
        self.slider_kind = kind
        x0, y0, x1, y1 = rect
        h = y1 - y0
        cy = (y0 + y1) // 2
        # 轨道
        scr.rrect([x0, cy - 7, x1, cy + 7], 7, fill=(52, 58, 74))
        w = int((x1 - x0) * max(0, min(vmax, value)) / float(vmax))
        if w > 0:
            scr.rrect([x0, cy - 7, x0 + max(14, w), cy + 7], 7,
                      fill=(90, 160, 250))
        # 圆钮
        kx = x0 + w
        r = max(9, h // 2)
        scr.d.ellipse([kx - r, cy - r, kx + r, cy + r], fill=(245, 248, 255),
                      outline=(180, 195, 220), width=2)
        if label:
            scr.text((x0, cy - r - 16), label, 15, (170, 185, 215),
                     anchor="lm", cn=True)

    def slider_hit(self, x, y):
        if not self.slider:
            return False
        x0, y0, x1, y1 = self.slider
        cy = (y0 + y1) // 2
        return (x0 - 14) <= x <= (x1 + 14) and abs(y - cy) <= 26

    def set_from_slider(self, x):
        if not self.slider:
            return
        x0, y0, x1, y1 = self.slider
        v = int(round(33.0 * (x - x0) / float(max(1, x1 - x0))))
        self.set_volume(v)

    # ---------- 提示音 ----------
    def _list_chimes(self):
        self.chimes = []
        try:
            import chime
            names = chime.STYLE_NAMES
            keys = list(chime.STYLES)
        except Exception:
            names, keys = {}, []
            try:
                keys = [os.path.splitext(f)[0]
                        for f in sorted(os.listdir(CHIME_DIR))
                        if f.endswith(".wav")]
            except Exception:
                pass
        for i, k in enumerate(keys):
            p = os.path.join(CHIME_DIR, "%s.wav" % k)
            if os.path.exists(p):
                self.chimes.append((k, names.get(k, k), p))
                if k == self.chime:
                    self.chime_sel = i

    def _chime_secs(self, p):
        try:
            import wave
            with wave.open(p, "rb") as w:
                return w.getnframes() / float(w.getframerate() or 1)
        except Exception:
            return 0.0

    # ---------- 后台 ----------
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

    def _refresh_quick(self):
        def fn():
            out = {}
            try:
                out["audio"] = _get(AUDIO_URL + "/health", 4).get("name", "在线")
            except Exception:
                out["audio"] = None
            try:
                h = _get(AGENT_URL + "/health", 4)
                out["agent"] = h.get("model") if h.get("ok") else None
            except Exception:
                out["agent"] = None
            out["ssid"] = _run("iwgetid -r 2>/dev/null") or "(未连)"
            out["ip"] = _run("hostname -I 2>/dev/null").split()[0:1]
            out["ip"] = out["ip"][0] if out["ip"] else "-"
            return out
        self._bg("refresh", fn)

    def _refresh_sys(self):
        def fn():
            d = {}

            def snap():
                parts = open("/proc/stat").readline().split()
                v = [int(x) for x in parts[1:]]
                idle = v[3] + (v[4] if len(v) > 4 else 0)
                return sum(v), idle
            try:
                t1, i1 = snap()
                time.sleep(0.35)                 # 两帧相减算占用率
                t2, i2 = snap()
                dt, di = t2 - t1, i2 - i1
                d["cpu"] = 0 if dt <= 0 else int(100 * (dt - di) / dt)
            except Exception:
                d["cpu"] = None
            try:
                d["load"] = open("/proc/loadavg").read().split()[0]
            except Exception:
                d["load"] = "-"
            try:
                for line in open("/proc/meminfo"):
                    k, val = line.split(":", 1)
                    if k in ("MemTotal", "MemAvailable"):
                        d[k] = int(val.strip().split()[0]) // 1024
            except Exception:
                pass
            d["temp"] = None
            for p in ("/sys/class/thermal/thermal_zone0/temp",
                      "/sys/class/hwmon/hwmon0/temp1_input",
                      "/sys/devices/soc0/amba/f8007100.adc/iio:device0/in_temp0_raw"):
                try:
                    raw = int(open(p).read().strip())
                    d["temp"] = (raw / 1000.0 if raw > 2000 else
                                 raw * 503.975 / 4096.0 - 273.15)
                    break
                except Exception:
                    continue
            d["uptime"] = _run("uptime -p 2>/dev/null") or "-"
            d["kernel"] = _run("uname -r")
            d["svc_audio"] = _run("systemctl is-active zynq-audio")
            d["svc_agent"] = _run("systemctl is-active zynq-agent")
            d["svc_desk"] = _run("systemctl is-active zynq-desktop")
            # 无线信号强度
            try:
                d["signal"] = _run(
                    "iwconfig wlan0 2>/dev/null | grep -o 'Signal level=[^ ]*'")
            except Exception:
                d["signal"] = "-"
            return d
        self._bg("sysinfo", fn)

    def play_chime(self, i):
        if not (0 <= i < len(self.chimes)):
            return
        self.chime_sel = i
        key, nm, path = self.chimes[i]

        def fn():
            _post(AUDIO_URL + "/volume", {"v": self.volume}, timeout=8)
            _post(AUDIO_URL + "/play", {"file": path}, timeout=30)
            return "试听「%s」%.2f 秒" % (nm, self._chime_secs(path))
        self._bg("play", fn)

    def set_chime(self):
        key, nm, path = self.chimes[self.chime_sel]

        def fn():
            import shutil
            shutil.copy(path, CHIME_DEFAULT)
            self.chime = key
            self.cfg["chime"] = key
            write_conf(self.cfg)
            return "★ 默认提示音已设为「%s」" % nm
        self._bg("setchime", fn)

    def set_volume(self, v):
        self.volume = max(0, min(33, v))
        self.cfg["volume"] = self.volume
        write_conf(self.cfg)

        def fn():
            _post(AUDIO_URL + "/volume", {"v": self.volume}, timeout=8)
            return "音量 %d" % self.volume
        self._bg("vol", fn)

    def tts_test(self):
        def fn():
            v, s = self.voice, self.speed
            out = "/tmp/_settings_tts.wav"
            r = _run("espeak-ng -v %s -s %d -w %s '你好，我是系统管家小白'"
                     % (v, s, out), timeout=30)
            if not os.path.exists(out):
                return "合成失败: %s" % r
            _post(AUDIO_URL + "/volume", {"v": self.volume}, timeout=8)
            _post(AUDIO_URL + "/play", {"file": out}, timeout=60)
            return "已用 %s / %d 试听" % (v, s)
        self._bg("tts", fn)

    def mic_test(self):
        def fn():
            import io
            import struct
            import wave
            b = None
            req = urllib.request.Request(
                AUDIO_URL + "/record",
                data=json.dumps({"secs": 1.5, "rate": 16000,
                                 "mono": True}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
            w = wave.open(io.BytesIO(b), "rb")
            n = w.getnframes()
            d = w.readframes(n)
            v = struct.unpack("<%dh" % (len(d) // 2), d)
            if not v:
                return "没采到数据"
            import math
            rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
            pk = max(abs(x) for x in v)
            self.mic_text = "RMS=%.1f  峰值=%d  采样=%d 帧" % (rms, pk, n)
            return "麦克风: " + self.mic_text
        self._bg("mic", fn)

    def restart_svc(self, which):
        def fn():
            r = _run("sudo systemctl restart zynq-%s" % which, timeout=40)
            time.sleep(3)
            st = _run("systemctl is-active zynq-%s" % which)
            return "zynq-%s -> %s %s" % (which, st, r[:80])
        self._bg("restart", fn)

    def pump(self):
        while True:
            try:
                name, res = self.q.get_nowait()
            except queue.Empty:
                return
            if name == "refresh":
                self.svc = res if isinstance(res, dict) else {}
                self.busy = ""
                continue
            if name == "sysinfo":
                self.sysinfo = res if isinstance(res, dict) else {}
                self.busy = ""
                continue
            self.busy = ""
            self.status = str(res)

    # ================================================ 页面定义
    def main_rows(self):
        ch = next((nm for k, nm, p in self.chimes if k == self.chime), "-")
        ssid = self.svc.get("ssid") or "-"
        return [
            ("sect", "声音"),
            ("row", "铃", "提示音", ch, "p_chime"),
            ("row", "音", "输出音量", str(self.volume), "p_vol"),
            ("sect", "语音助手"),
            ("row", "话", "说话音色与语速", "%s / %d" % (self.voice, self.speed),
             "p_voice"),
            ("row", "麦", "麦克风自检", "只录音、不放音", "p_mic"),
            ("sect", "连接与系统"),
            ("row", "网", "无线网络", ssid, "p_net"),
            ("row", "统", "系统信息", "CPU / 内存 / 温度", "p_sys"),
            ("row", "服", "后台服务", "-", "p_svc"),
            ("row", "壁", "壁纸", "", "p_wall"),
            ("sect", "关于"),
            ("row", "关", "关于本机", "系统管家小白", "p_about"),
        ]

    def draw_list(self, scr, rows, top=None):
        """画一个 iOS/华为 风格的设置列表，返回可点区域列表"""
        y = top or (HDR + 10)
        out = []
        for it in rows:
            if it[0] == "sect":
                scr.text((CARD_X0 + 8, y + SECT_H - 6), it[1], 15,
                         (150, 165, 195), anchor="lm", cn=True)
                y += SECT_H
                continue
            _, ch, label, value, act = it
            r = [CARD_X0, y, CARD_X1, y + ROW_H - 4]
            scr.rrect(r, 10, fill=(30, 34, 48), outline=(52, 60, 82))
            badge(scr, r[0] + 10, y + (ROW_H - 4 - 32) // 2, 32, ch)
            scr.text((r[0] + 54, y + (ROW_H - 4) // 2), label, 20,
                     (236, 240, 250), anchor="lm", cn=True)
            if value:
                scr.text((r[2] - 34, y + (ROW_H - 4) // 2), str(value), 17,
                         (150, 168, 200), anchor="rm", cn=True)
            scr.text((r[2] - 16, y + (ROW_H - 4) // 2), ">", 20,
                     (110, 125, 155), anchor="rm")
            out.append((r, act))
            y += ROW_H
        return out

    def draw(self, scr):
        scr.clear((18, 20, 30))
        page = self.pages[-1]
        title = {"main": "设置", "p_chime": "提示音", "p_vol": "输出音量",
                 "p_voice": "说话音色与语速", "p_mic": "麦克风自检",
                 "p_net": "无线网络", "p_sys": "系统信息",
                 "p_svc": "后台服务", "p_about": "关于本机"}.get(page, "设置")
        header(scr, title)
        rows = []

        if page == "main":
            rows = self.draw_list(scr, self.main_rows())

        elif page == "p_chime":
            # ★ 两列排（14 个提示音一列放不下，会溢出屏幕）
            rh = 42
            nrow = 7
            colw = (CARD_X1 - CARD_X0 - 16) // 2
            top = HDR + 10
            secs = self._chime_secs
            for i, (k, nm, p) in enumerate(self.chimes):
                col = i // nrow
                rw = i % nrow
                if col > 1:
                    break
                cx0 = CARD_X0 + col * (colw + 16)
                cx1 = cx0 + colw
                y = top + rw * rh
                r = [cx0, y, cx1, y + rh - 3]
                cur = (i == self.chime_sel)
                scr.rrect(r, 9, fill=(46, 60, 96) if cur else (30, 34, 48),
                          outline=(90, 140, 230) if cur else (52, 60, 82))
                if k == self.chime:
                    scr.text((r[0] + 10, (r[1] + r[3]) // 2), "★", 16,
                             (255, 214, 90), anchor="lm")
                scr.text((r[0] + 34, (r[1] + r[3]) // 2), nm, 18,
                         (240, 244, 255), anchor="lm", cn=True)
                scr.text((r[2] - 46, (r[1] + r[3]) // 2), "%.2fs" % secs(p), 14,
                         (150, 170, 200), anchor="rm")
                rows.append((r, ("chime", i)))
            y = top + nrow * rh + 22
            self.draw_slider(scr, [CARD_X0 + 40, y, CARD_X1 - 30, y + 22],
                             self.volume, 33,
                             label="试听音量  %d（可拖动）" % self.volume,
                             kind="volume")
            y += 48
            r1 = [CARD_X0, y, CARD_X0 + 240, y + 44]
            r2 = [CARD_X0 + 254, y, CARD_X0 + 454, y + 44]
            btn(scr, r1, "设为默认", fill=(40, 130, 80), size=19, cn=True,
                radius=10)
            btn(scr, r2, "停止", fill=(120, 60, 60), size=19, cn=True,
                radius=10)
            rows.append((r1, "setchime"))
            rows.append((r2, "stop"))
            scr.text((CARD_X0 + 470, y + 22),
                     "点名字试听 · 带(响)的明显更响 · 最大声=硬件极限", 15,
                     (170, 185, 215), anchor="lm", cn=True)

        elif page == "p_vol":
            y = HDR + 26
            scr.text((W // 2, y), "输出音量", 22, (170, 185, 215),
                     anchor="mm", cn=True)
            y += 42
            scr.text((W // 2, y), "%d" % self.volume, 46, (245, 248, 255),
                     anchor="mm", cn=True)
            y += 52
            # ★ 可拖动滑块：按住圆钮左右拖
            self.draw_slider(scr, [150, y, W - 150, y + 30], self.volume, 33,
                             label="拖动滑块，或点轨道任意位置",
                             kind="volume")
            y += 74
            # 微调（★ 必须 btn() 画出来 —— 只 append 点击区域会"能点但看不见"）
            for i, d in enumerate((-5, -1, +1, +5)):
                bx = 150 + i * 108
                r = [bx, y, bx + 94, y + 48]
                btn(scr, r, "%+d" % d, fill=(58, 66, 88), size=20, cn=True,
                    radius=9, outline=(86, 98, 128))
                rows.append((r, ("vol", d)))
            y += 62
            # 预设
            presets = [("静音", 0), ("低", 10), ("中", 20), ("高", 28), ("最大", 33)]
            for i, (nm, v) in enumerate(presets):
                bx = 150 + i * 132
                r = [bx, y, bx + 118, y + 46]
                on = (self.volume == v)
                btn(scr, r, nm, fill=(60, 110, 190) if on else (46, 52, 70),
                    size=18, cn=True, radius=9,
                    outline=(120, 180, 255) if on else (70, 80, 105))
                rows.append((r, ("volset", v)))
            y += 62
            r1 = [150, y, 470, y + 50]
            r2 = [486, y, 806, y + 50]
            btn(scr, r1, "试听当前提示音", fill=(46, 120, 180), size=18,
                cn=True, radius=10)
            btn(scr, r2, "停止", fill=(120, 60, 60), size=19, cn=True,
                radius=10)
            rows.append((r1, "testchime"))
            rows.append((r2, "stop"))

        elif page == "p_voice":
            y = HDR + 14
            scr.text((CARD_X0 + 8, y), "音色（espeak-ng 语音）", 15,
                     (150, 165, 195), anchor="lm", cn=True)
            y += 26
            for v, nm in (("cmn", "普通话(女)"), ("zh", "普通话(录音)")):
                r = [CARD_X0, y, CARD_X1, y + ROW_H - 4]
                cur = (v == self.voice)
                scr.rrect(r, 10, fill=(46, 60, 96) if cur else (30, 34, 48),
                          outline=(90, 140, 230) if cur else (52, 60, 82))
                scr.text((r[0] + 16, (r[1] + r[3]) // 2), nm, 20,
                         (240, 244, 255), anchor="lm", cn=True)
                scr.text((r[2] - 20, (r[1] + r[3]) // 2), v, 16,
                         (150, 170, 205), anchor="rm", mono=True)
                rows.append((r, ("voice", v)))
                y += ROW_H
            y += 8
            scr.text((CARD_X0 + 8, y), "语速  %d（80~220）" % self.speed, 15,
                     (150, 165, 195), anchor="lm", cn=True)
            y += 26
            r1 = [CARD_X0, y, CARD_X0 + 150, y + 48]
            r2 = [CARD_X0 + 162, y, CARD_X0 + 312, y + 48]
            r3 = [CARD_X0 + 336, y, CARD_X0 + 576, y + 48]
            btn(scr, r1, "慢一点 -20", fill=(58, 66, 88), size=17, cn=True,
                radius=9, outline=(86, 98, 128))
            btn(scr, r2, "快一点 +20", fill=(58, 66, 88), size=17, cn=True,
                radius=9, outline=(86, 98, 128))
            btn(scr, r3, "试听这句", fill=(46, 120, 180), size=18, cn=True,
                radius=10)
            rows.append((r1, ("speed", -20)))
            rows.append((r2, ("speed", 20)))
            rows.append((r3, "ttstest"))
            y += 62
            scr.text((CARD_X0 + 8, y),
                     "当前: %s / %d        （试听会说一句「你好，我是系统管家小白」）"
                     % (self.voice, self.speed), 15, (150, 165, 195),
                     anchor="lm", cn=True)

        elif page == "p_mic":
            y = HDR + 20
            scr.text((W // 2, y + 10),
                     "麦克风自检（只录音，喇叭不会响）", 22, (236, 240, 250),
                     anchor="mm", cn=True)
            y += 70
            r1 = [320, y, 704, y + 56]
            btn(scr, r1, "录 1.5 秒看看电平", fill=(46, 130, 90), size=20,
                cn=True, radius=12)
            rows.append((r1, "mictest"))
            y += 76
            if self.mic_text:
                scr.text((W // 2, y + 10), self.mic_text, 20, (120, 240, 200),
                         anchor="mm", cn=True)
            else:
                scr.text((W // 2, y + 10),
                         "按上面按钮录 1.5 秒，看有没有电平", 17,
                         (150, 165, 195), anchor="mm", cn=True)

        elif page == "p_net":
            y = HDR + 14
            info = [("网络名称(SSID)", self.svc.get("ssid") or "-"),
                    ("IP 地址", self.svc.get("ip") or "-"),
                    ("无线信号", self.svc.get("signal") or "-")]
            for k, v in info:
                r = [CARD_X0, y, CARD_X1, y + ROW_H - 4]
                scr.rrect(r, 10, fill=(30, 34, 48), outline=(52, 60, 82))
                scr.text((r[0] + 16, (r[1] + r[3]) // 2), k, 19,
                         (236, 240, 250), anchor="lm", cn=True)
                scr.text((r[2] - 16, (r[1] + r[3]) // 2), str(v), 18,
                         (150, 190, 240), anchor="rm", cn=True)
                y += ROW_H
            y += 12
            scr.text((CARD_X0 + 8, y),
                     "改 WiFi 请用桌面上的「WiFi」图标（这里只显示状态）",
                     15, (150, 165, 195), anchor="lm", cn=True)

        elif page == "p_sys":
            y = HDR + 14
            si = self.sysinfo or {}
            if not si:
                self._refresh_sys()
                scr.text((W // 2, 300), "正在读取 ...", 20,
                         (180, 195, 220), anchor="mm", cn=True)
            pairs = [("CPU 占用", ("%d%%" % si["cpu"]) if si.get("cpu") is not None else "-"),
                     ("1 分钟负载", si.get("load", "-")),
                     ("内存可用", "%s MB / %s MB" % (si.get("MemAvailable", "-"),
                                                     si.get("MemTotal", "-"))),
                     ("芯片温度", ("%.1f °C" % si["temp"]) if si.get("temp") else "-"),
                     ("运行时长", si.get("uptime", "-")),
                     ("内核", si.get("kernel", "-"))]
            for k, v in pairs:
                r = [CARD_X0, y, CARD_X1, y + ROW_H - 4]
                scr.rrect(r, 10, fill=(30, 34, 48), outline=(52, 60, 82))
                scr.text((r[0] + 16, (r[1] + r[3]) // 2), k, 19,
                         (236, 240, 250), anchor="lm", cn=True)
                scr.text((r[2] - 16, (r[1] + r[3]) // 2), str(v), 18,
                         (160, 200, 240), anchor="rm", cn=True)
                y += ROW_H
            y += 8
            r1 = [CARD_X0, y, CARD_X0 + 200, y + 46]
            btn(scr, r1, "刷新", fill=(58, 66, 88), size=18, cn=True,
                radius=9, outline=(86, 98, 128))
            rows.append((r1, "refreshsys"))
            scr.text((CARD_X0 + 220, y + 23),
                     "实时数据，点「刷新」重读", 15, (150, 165, 195),
                     anchor="lm", cn=True)

        elif page == "p_svc":
            y = HDR + 14
            si = self.sysinfo or {}
            if not si:
                self._refresh_sys()
            items = [("zynq-audio", si.get("svc_audio", "-"), "音频服务(独占)"),
                     ("zynq-agent", si.get("svc_agent", "-"), "系统管家小白"),
                     ("zynq-desktop", si.get("svc_desk", "-"), "桌面")]
            for nm, st, desc in items:
                r = [CARD_X0, y, CARD_X1, y + ROW_H - 4]
                scr.rrect(r, 10, fill=(30, 34, 48), outline=(52, 60, 82))
                ok = (st == "active")
                scr.rrect([r[0] + 14, (r[1] + r[3]) // 2 - 7,
                           r[0] + 28, (r[1] + r[3]) // 2 + 7], 7,
                          fill=(52, 199, 89) if ok else (255, 69, 58))
                scr.text((r[0] + 42, (r[1] + r[3]) // 2), nm, 19,
                         (236, 240, 250), anchor="lm", mono=True)
                scr.text((r[0] + 300, (r[1] + r[3]) // 2), desc, 15,
                         (150, 165, 195), anchor="lm", cn=True)
                scr.text((r[2] - 16, (r[1] + r[3]) // 2), st, 17,
                         (120, 240, 160) if ok else (255, 140, 140),
                         anchor="rm", mono=True)
                y += ROW_H
            y += 10
            r1 = [CARD_X0, y, CARD_X0 + 200, y + 46]
            r2 = [CARD_X0 + 214, y, CARD_X0 + 414, y + 46]
            r3 = [CARD_X0 + 428, y, CARD_X0 + 588, y + 46]
            btn(scr, r1, "重启音频服务", fill=(150, 96, 40), size=17, cn=True,
                radius=9)
            btn(scr, r2, "重启 Agent", fill=(150, 96, 40), size=17, cn=True,
                radius=9)
            btn(scr, r3, "刷新", fill=(58, 66, 88), size=18, cn=True,
                radius=9, outline=(86, 98, 128))
            rows.append((r1, "restart_audio"))
            rows.append((r2, "restart_agent"))
            rows.append((r3, "refreshsys"))

        elif page == "p_about":
            y = HDR + 20
            lines = ["系统管家小白  v0.1",
                     "运行在正点原子 领航者 ZYNQ7020",
                     "Zynq-7020 (双核 Cortex-A9 + FPGA)",
                     "Ubuntu 20.04 armv7l",
                     "内核 " + (self.sysinfo.get("kernel") or "-"),
                     "",
                     "音频: ES8388 + 自研 PL 通路（全用户态驱动）",
                     "语音: 离线 vosk 识别 + 离线 espeak-ng 合成"]
            for ln in lines:
                scr.text((CARD_X0 + 16, y), ln, 19, (215, 225, 245),
                         anchor="lm", cn=True)
                y += 34

        # 二级页的返回已在 header 的 back_hit 里处理
        if self.busy:
            scr.text((W - 34, HDR + 84), "工作中: " + self.busy, 15,
                     (250, 200, 120), anchor="rm", cn=True)
        if self.status:
            scr.text((CARD_X0, H - 14), self.status[-96:], 15,
                     (200, 220, 250), anchor="lm", cn=True)
        return rows


def run(scr, touch):
    s = Settings()

    def do_click(x, y, rows):
        """处理一次点击；返回 True 表示要退出这个 App"""
        if back_hit(x, y):
            if len(s.pages) > 1:
                s.pages.pop()
                s.status = ""
                return False
            return True
        for r, act in rows:
            if not hit(r, x, y):
                continue
            if isinstance(act, tuple):
                k, v = act
                if k == "chime":
                    s.play_chime(v)
                elif k == "vol":
                    s.set_volume(s.volume + v)
                elif k == "volset":
                    s.set_volume(v)
                elif k == "voice":
                    s.voice = v
                    s.cfg["voice"] = v
                    write_conf(s.cfg)
                    s.status = "音色设为 " + v
                elif k == "speed":
                    s.speed = max(80, min(220, s.speed + v))
                    s.cfg["speed"] = s.speed
                    write_conf(s.cfg)
                    s.status = "语速 %d" % s.speed
                return False
            if act.startswith("p_"):
                if act in ("p_sys", "p_svc"):
                    s._refresh_sys()
                if act == "p_net":
                    s._refresh_quick()
                s.pages.append(act)
            elif act == "setchime":
                s.set_chime()
            elif act == "stop":
                def _st():
                    _post(AUDIO_URL + "/stop", {})
                    return "已停止播放"
                s._bg("stop", _st)
            elif act == "testchime":
                s.play_chime(s.chime_sel)
            elif act == "ttstest":
                s.tts_test()
            elif act == "mictest":
                s.mic_test()
            elif act == "refreshsys":
                s._refresh_sys()
                s.status = "正在刷新..."
            elif act == "restart_audio":
                s.restart_svc("audio")
            elif act == "restart_agent":
                s.restart_svc("agent")
            return False
        return False

    while True:
        s.pump()
        rows = s.draw(scr)
        scr.flush()
        # ★ 用 poll(move=True) 才能拿到 down/move/up —— 拖动滑块要靠它
        ev = touch.poll(move=True)
        if not ev:
            time.sleep(0.02)
            continue
        kind = ev[0]
        if kind == "tap":
            if do_click(ev[1], ev[2], rows):
                return
            continue
        x, y = ev[1], ev[2]
        if kind == "down":
            if s.slider_hit(x, y):
                s.dragging = True
                s.set_from_slider(x)
            continue
        if kind == "move":
            if s.dragging:
                s.set_from_slider(x)
            continue
        if kind == "up":
            if s.dragging:
                s.dragging = False
                s.status = "音量 %d" % s.volume
                continue
            # 没有拖动 -> 当成一次点击（真实触摸屏点按也是 down..up 两个事件）
            if do_click(x, y, rows):
                return
