#!/usr/bin/env python3
"""HTTP compatibility layer for the board's official ES8388 ALSA sound card.

2026-09-29 修复（由 DSH 会话追加）：
  ① 播放前做格式转换。硬件【只接受 44100Hz / 2ch / 16bit】，
     其他格式 aplay 直接报 "Unable to install hw params"，
     而且失败期间会占住声卡，导致后续所有播放都 "Device or resource busy"。
     板上没有 sox/ffmpeg，所以用标准库 audioop 自己转。
     ★ 这正是"点某个文件后整个播放器就播不了"的根因。
  ② proc.communicate() 加超时，避免卡死。
  ③ self.proc 的清空放进 finally，异常路径也不会漏。
"""

import audioop
import array
import io
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("AUDIO_SVC_PORT", "8767"))

# 硬件唯一接受的格式（实测：44100/2ch/16bit 之外的都会 set_params 失败）
PLAY_RATE = 44100
PLAY_CHANNELS = 2
PLAY_WIDTH = 2


class Audio:
    def __init__(self):
        self.lock = threading.RLock()
        self.proc = None
        self.volume = 33
        self.last_error = ""

    def state(self):
        with self.lock:
            return {"ok": True, "backend": "alsa", "playing": bool(self.proc),
                    "volume": self.volume, "last_error": self.last_error}

    def stop(self):
        with self.lock:
            proc = self.proc
            self.proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

    def set_volume(self, value):
        value = max(0, min(33, int(value)))
        for control in ("Output 1", "Output 2"):
            subprocess.run(["amixer", "-q", "-c", "0", "sset", control,
                            str(value)], check=True, timeout=8)
        with self.lock:
            self.volume = value
        return value

    # ------------------------------------------------------------------
    #  格式转换：把任意 WAV 变成硬件能放的 44100/2ch/16bit
    # ------------------------------------------------------------------
    def prepare(self, path):
        """返回 (可播放路径, 需要删除的临时文件或None, 时长秒)"""
        with wave.open(path, "rb") as w:
            ch = w.getnchannels()
            sw = w.getsampwidth()
            rate = w.getframerate()
            nframes = w.getnframes()
            raw = w.readframes(nframes)

        if rate <= 0:
            raise RuntimeError("WAV 采样率非法")
        seconds = nframes / float(rate)

        # 已经是目标格式，直接用原文件
        if ch == PLAY_CHANNELS and sw == PLAY_WIDTH and rate == PLAY_RATE:
            return path, None, seconds

        # ① 位宽 -> 16bit
        if sw != PLAY_WIDTH:
            if sw not in (1, 2, 3, 4):
                raise RuntimeError("不支持的位宽 %d bit" % (sw * 8))
            raw = audioop.lin2lin(raw, sw, PLAY_WIDTH)

        # ② 声道 -> 2
        if ch == 1:
            raw = audioop.tostereo(raw, PLAY_WIDTH, 1, 1)
        elif ch > PLAY_CHANNELS:
            # 只保留前两个声道
            frame = PLAY_WIDTH * ch
            keep = PLAY_WIDTH * PLAY_CHANNELS
            out = bytearray()
            for i in range(0, len(raw) - frame + 1, frame):
                out += raw[i:i + keep]
            raw = bytes(out)
        elif ch < 1:
            raise RuntimeError("声道数非法")

        # ③ 采样率 -> 44100
        if rate != PLAY_RATE:
            raw, _ = audioop.ratecv(raw, PLAY_WIDTH, PLAY_CHANNELS,
                                    rate, PLAY_RATE, None)

        fd, tmp = tempfile.mkstemp(prefix="alsa_conv_", suffix=".wav")
        os.close(fd)
        with wave.open(tmp, "wb") as w:
            w.setnchannels(PLAY_CHANNELS)
            w.setsampwidth(PLAY_WIDTH)
            w.setframerate(PLAY_RATE)
            w.writeframes(raw)
        return tmp, tmp, seconds

    def play_file(self, path):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)

        playable, tmp, seconds = self.prepare(path)
        proc = None
        try:
            self.stop()
            proc = subprocess.Popen(["aplay", playable],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            with self.lock:
                self.proc = proc
            try:
                # ② 加超时：正常时长 + 30 秒余量
                _, err = proc.communicate(timeout=seconds + 30.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    _, err = proc.communicate(timeout=5)
                except Exception:
                    err = b""
                raise RuntimeError("播放超时，已强制终止")
            if proc.returncode:
                raise RuntimeError(err.decode(errors="replace").strip())
            return seconds
        finally:
            # ③ 无条件清理，异常路径也不漏
            with self.lock:
                if self.proc is proc:
                    self.proc = None
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def play_tone(self, freq, seconds, amp):
        freq = max(50.0, min(10000.0, float(freq)))
        seconds = max(0.1, min(10.0, float(seconds)))
        amp = max(0.0, min(0.5, float(amp)))
        fd, path = tempfile.mkstemp(prefix="alsa_tone_", suffix=".wav")
        os.close(fd)
        try:
            with wave.open(path, "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                frames = bytearray()
                for i in range(int(seconds * 44100)):
                    s = int(32767 * amp * math.sin(2 * math.pi * freq * i / 44100))
                    frames += struct.pack("<hh", s, s)
                wav.writeframes(frames)
            return self.play_file(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def capture(self, seconds, rate, mono):
        seconds = max(0.1, min(60.0, float(seconds)))
        rate = max(8000, min(48000, int(rate)))
        duration = int(math.ceil(seconds))
        raw = subprocess.run(
            ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
             "-r", "44100", "-d", str(duration), "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=duration + 10)
        if raw.returncode:
            raise RuntimeError(raw.stderr.decode(errors="replace").strip())
        source = raw.stdout[:int(seconds * 44100) * 8]
        samples = array.array("i")
        samples.frombytes(source[:len(source) & ~3])
        pcm = array.array("h")
        # ★★★ 2026-10-01 修复（由 DSH 会话追加）★★★
        #
        #   原来这里是   samples[i] >> 8
        #   那是"24 位数据【左对齐】放在高 3 字节"的算法。
        #
        #   但本板 I2S 采集实际是【右对齐在低 3 字节，而且没有做符号扩展】：
        #       字节 FE FF FF 00  ->  int32 = 0x00FFFFFE
        #       它代表的是 24 位有符号数 -2（0xFFFFFE），
        #       可是第 4 字节是 0x00 而不是 0xFF，所以直接当 int32 读会得到
        #       16777214 这个巨大的正数。
        #
        #   原来的 >> 8 会把它变成 0x0000FFFF = 65535，再削顶到 32767，
        #   于是录出来的"音频"只有几个满量程的固定值 —— 就是用户看到的
        #   "录音文件全是噪声/爆音"。
        #
        #   正确做法：先从 bit23 手动符号扩展，再右移 8 位降到 16 bit。
        def s24_to_s16(v):
            if v >= 0x800000:          # bit23 = 1 -> 负数的 24 位表示
                v -= 0x1000000         # 扩展到 32 位有符号
            elif v > 0x7FFFFF:
                v = 0x7FFFFF           # 防御：异常值夹到 24 位范围
            s = v >> 8
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            return s

        for i in range(0, len(samples) - 1, 2):
            left = s24_to_s16(samples[i])
            right = s24_to_s16(samples[i + 1])
            if mono:
                pcm.append((left + right) // 2)
            else:
                pcm.extend((left, right))
        channels = 1 if mono else 2
        payload = pcm.tobytes()
        if rate != 44100:
            payload, _ = audioop.ratecv(payload, 2, channels, 44100, rate, None)
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(payload)
        return out.getvalue()


AUDIO = Audio()


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status, value):
        self.send_data(status, json.dumps(value).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            self.send_json(200, {"ok": True, "name": "ES8388 ALSA 音频服务",
                                 "port": PORT})
        elif path == "/state":
            self.send_json(200, AUDIO.state())
        else:
            self.send_json(404, {"ok": False, "error": "no such path"})

    def do_POST(self):
        try:
            size = min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)
            args = json.loads(self.rfile.read(size) or b"{}")
            path = self.path.split("?", 1)[0]
            if path == "/stop":
                AUDIO.stop()
                return self.send_json(200, {"ok": True})
            if path == "/volume":
                value = AUDIO.set_volume(args.get("v", 33))
                return self.send_json(200, {"ok": True, "volume": value})
            if path in ("/play", "/say"):
                if args.get("file"):
                    seconds = AUDIO.play_file(args["file"])
                else:
                    seconds = AUDIO.play_tone(args.get("tone", 1000),
                                              args.get("secs", 1),
                                              args.get("amp", 0.3))
                return self.send_json(200, {"ok": True, "secs": round(seconds, 3)})
            if path == "/record":
                data = AUDIO.capture(args.get("secs", 3), args.get("rate", 16000),
                                     args.get("mono", True))
                return self.send_data(200, data, "audio/wav")
            if path == "/selftest":
                # ★★★ 2026-10-02 接上真的声学自测（原来是占位实现，
                #   音乐 App 的「自检」按钮点了永远说"请人工试听音乐"）
                #
                # 原理：放一个已知频率的纯音 -> 麦克风录回来 -> 算
                #       play/base 的能量比。用的是比值不是绝对能量
                #       （文档记录：基线 100Hz 工频谐波能量极大，
                #        找最大能量会找错）。
                #
                # ★ 实测正常值：990Hz 时比值 +13.5 dB（优秀）
                #   采集坏了（ES8388 的 0x0A 被设成 LINE 输入）时：-90 dB 级
                #
                # ★ 注意：这个自测【会出声】。静音锁开着就拒绝，不硬放。
                if os.path.exists("/etc/zynq-silent"):
                    return self.send_json(200, {
                        "ok": False, "freq": args.get("freq"),
                        "verdict": "静音模式开着，声学自测要放音 —— 先解除静音"})
                try:
                    freq = float(args.get("freq", 990.53))
                except Exception:
                    freq = 990.53
                try:
                    secs = float(args.get("secs", 1.2))
                except Exception:
                    secs = 1.2
                try:
                    vol = int(args.get("vol", 55))
                except Exception:
                    vol = 55

                # ★ 自测要用整个声卡，先把自己的播放停掉释放设备
                try:
                    AUDIO.stop()
                except Exception:
                    pass

                out = {}
                try:
                    import subprocess as _sp
                    p = _sp.run(
                        ["/usr/bin/python3", "/home/zynq/acoustic_selftest.py",
                         "--freq", str(freq), "--secs", str(secs),
                         "--vol", str(vol), "--json"],
                        stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=90)
                    txt = (p.stdout or b"").decode("utf-8", "replace")
                    # ★ 脚本会把 JSON 打在 __JSON__ 那一行（见 acoustic_selftest.py）
                    import json as _json
                    for ln in reversed(txt.strip().split("\n")):
                        ln = ln.strip()
                        if ln.startswith("__JSON__"):
                            out = _json.loads(ln[len("__JSON__"):])
                            break
                    if not out:
                        out = {"ok": False,
                               "verdict": "自测脚本没给出结果",
                               "raw": txt[-300:]}
                except Exception as e:
                    out = {"ok": False,
                           "verdict": "自测跑不起来：%s: %s"
                                      % (type(e).__name__, e)}
                return self.send_json(200, out)
            return self.send_json(404, {"ok": False, "error": "no such path"})
        except Exception as exc:
            # 出错时一定要确保设备被释放，否则后续播放全部 "busy"
            try:
                AUDIO.stop()
            except Exception:
                pass
            AUDIO.last_error = "%s: %s" % (type(exc).__name__, exc)
            try:
                self.send_json(500, {"ok": False, "error": AUDIO.last_error})
            except Exception:
                pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()
