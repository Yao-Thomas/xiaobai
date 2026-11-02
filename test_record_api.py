#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_record_api.py —— 端到端测音频服务的 /record 接口

★ 这是最贴近用户的一测：
   音乐 App 里点「录音 N 秒」走的就是 POST /record
   （apps_music.py:167  _post_raw(AUDIO_URL + "/record", {...})）

如果这条路能录到有信号的音频，那 B1 就算通了；
如果录到的是 -137 dBFS 静音，才是真的要修。

顺便也测 /selftest（放音+录音+比较），那是声学自测的雏形。

用法:
    sudo python3 test_record_api.py
"""
import array
import json
import math
import os
import struct
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8767"


def post_raw(path, payload, timeout=120):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def post_json(path, payload, timeout=120):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_json(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def analyze(data, label):
    """分析 WAV 字节流（支持 16/24/32 位）"""
    if len(data) < 44:
        print("   %s: 数据太短 (%d 字节)" % (label, len(data)))
        return None
    # 找 fmt / data
    pos = 12
    fmt = None
    raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        csz = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + csz]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            raw = body
        pos += 8 + csz + (csz & 1)
    if not fmt or raw is None:
        print("   %s: 不是合法 WAV（头部: %s）" % (label, data[:16].hex()))
        return None
    afmt, nch, rate, brate, balign, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    n = len(raw) // balign
    if bits == 16:
        a = array.array("h")
        a.frombytes(raw[:n * nch * 2])
        full = 32768.0
    elif bits == 24:
        a = array.array("i")
        a.frombytes(raw[:n * nch * 4])
        for k in range(len(a)):
            if a[k] >= 0x800000:
                a[k] -= 0x1000000
        full = 8388608.0
    elif bits == 32:
        a = array.array("i")
        a.frombytes(raw[:n * nch * 4])
        full = 2147483648.0
    else:
        print("   %s: 不支持位深 %d" % (label, bits))
        return None

    res = []
    for c in range(nch):
        xs = a[c::nch]
        if not xs:
            res.append(-999.0)
            continue
        rms = math.sqrt(sum(float(x) * x for x in xs) / len(xs))
        res.append(20 * math.log10(rms / full) if rms > 0 else -999.0)
    pk = max(abs(x) for x in a) if a else 0
    uniq = len(set(a))
    print("   %-16s %d Hz / %d ch / %d bit / %d 帧 (%.2f 秒)"
          % (label, rate, nch, bits, n, n / float(rate)))
    print("                    每声道 dBFS: %s   峰值=%d  不同值=%d"
          % (", ".join("%.1f" % v for v in res), pk, uniq))
    return res


def main():
    print("=" * 78)
    print(" 端到端测音频服务 /record（音乐 App 录音按钮走的就是这条）")
    print("=" * 78)

    try:
        st = get_json("/state")
        print("\n>>> 服务状态: %s" % json.dumps(st, ensure_ascii=False)[:200])
    except Exception as e:
        print("\n>>> 服务状态读取失败: %s" % e)
        return

    print("\n>>> 1. POST /record  secs=3 rate=16000 mono=True")
    try:
        wav = post_raw("/record", {"secs": 3.0, "rate": 16000, "mono": True},
                       timeout=60)
        print("   返回 %d 字节" % len(wav))
        with open("/tmp/api_rec.wav", "wb") as f:
            f.write(wav)
        r = analyze(wav, "录音")
        if r and r[0] < -100:
            print("   ★★★ 是数字静音 —— 这条录音路是坏的")
        elif r:
            print("   ✓ 有信号")
    except Exception as e:
        print("   失败: %s" % e)

    print("\n>>> 2. POST /record  secs=3 rate=44100 mono=False")
    try:
        wav = post_raw("/record", {"secs": 3.0, "rate": 44100, "mono": False},
                       timeout=60)
        print("   返回 %d 字节" % len(wav))
        r = analyze(wav, "录音44k")
    except Exception as e:
        print("   失败: %s" % e)

    print("\n>>> 3. POST /selftest（放音 + 录音 + 比较）")
    try:
        d = post_json("/selftest", {"freq": 990.53, "secs": 1.2}, timeout=120)
        print("   " + json.dumps(d, ensure_ascii=False)[:400])
    except Exception as e:
        print("   失败: %s" % e)

    print()
    print("=" * 78)
    print("★ 判读：")
    print("   /record 返回的不是静音 -> 录音通路 OK，B1 可以做（问题只在自检/分析）")
    print("   /record 是 -137 静音    -> 录音路确实坏了，要修（PL I2S RX 没配）")


if __name__ == "__main__":
    main()
