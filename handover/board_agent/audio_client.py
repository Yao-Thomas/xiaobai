#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_client.py —— 与板载音频服务 (127.0.0.1:8767) 通信。

音频硬件是**全局独占资源**，所以 Agent 不直接碰寄存器、也不直接开 /dev/mem，
一律通过这个服务。服务地址可用环境变量 AUDIO_SVC 覆盖。
"""
import json
import os
import urllib.request

BASE = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767").rstrip("/")


class AudioError(Exception):
    pass


def _req(path, data=None, timeout=120, raw=False):
    url = BASE + path
    if data is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read()
    except Exception as e:
        raise AudioError("音频服务不可用 (%s): %s: %s"
                         % (url, type(e).__name__, e))
    if raw:
        return body
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        raise AudioError("音频服务返回了非 JSON: %r" % body[:200])


def health():
    return _req("/health", timeout=6)


def alive():
    try:
        return bool(health().get("ok"))
    except Exception:
        return False


def state():
    return _req("/state", timeout=8)


def volume(v):
    return _req("/volume", {"v": int(v)}, timeout=10)


def play_tone(freq=1000, secs=1.0, amp=0.4):
    return _req("/play", {"tone": float(freq), "secs": float(secs),
                          "amp": float(amp)}, timeout=float(secs) + 90)


def play_file(path):
    if not os.path.isfile(path):
        raise AudioError("文件不存在: %s" % path)
    return _req("/play", {"file": path}, timeout=600)


def record(secs=3.0, rate=16000, mono=True):
    """录一段，返回 WAV 字节。"""
    return _req("/record", {"secs": float(secs), "rate": int(rate),
                            "mono": bool(mono)},
                timeout=float(secs) + 240, raw=True)


def record_to(path, secs=3.0, rate=16000, mono=True):
    b = record(secs, rate, mono)
    with open(path, "wb") as f:
        f.write(b)
    return path


def selftest(freq=1000, secs=1.2):
    return _req("/selftest", {"freq": float(freq), "secs": float(secs)},
                timeout=240)


def stop():
    return _req("/stop", {}, timeout=10)


if __name__ == "__main__":
    import sys
    if not alive():
        print("音频服务没起来（%s）。先在板上跑：sudo python3 ui/audio_svc.py" % BASE)
        sys.exit(1)
    print(json.dumps(state(), ensure_ascii=False, indent=2))
