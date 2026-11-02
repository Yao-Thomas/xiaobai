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
        for i in range(0, len(samples) - 1, 2):
            left = max(-32768, min(32767, samples[i] >> 8))
            right = max(-32768, min(32767, samples[i + 1] >> 8))
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
                return self.send_json(200, {"ok": False,
                                            "verdict": "请人工试听音乐"})
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
