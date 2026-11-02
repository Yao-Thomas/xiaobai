#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ws_flow.py —— 对比"直连 DSH"和"走我的代理"时 WebSocket 的数据流

手机端日志显示 /api/remote.mux 握手返回 101 成功，所以要么是
  (a) 握手之后数据不流（我的盲转发有问题），要么
  (b) 数据在流，问题在别处（比如手机窄屏把会话侧栏折叠了）。
这个脚本读 6 秒，看两个通道各收到多少字节。
"""
import base64
import hashlib
import http.cookiejar
import os
import socket
import sys
import time
import urllib.request

sys.path.insert(0, ".")
from dsh_proxy import load_secret, make_auth_cookie          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

secret = load_secret()
name, val = make_auth_cookie(secret)


def ws_probe(host, port, cookie, secs=6.0):
    key = base64.b64encode(os.urandom(16)).decode()
    try:
        s = socket.create_connection((host, port), timeout=6)
    except OSError as e:
        return "连不上(%s)" % e, b""
    hdr = ("GET /api/remote.mux HTTP/1.1\r\n"
           "Host: %s:%d\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
           "Origin: http://%s:%d\r\n"
           "Cookie: %s\r\n\r\n" % (host, port, key, host, port, cookie))
    s.sendall(hdr.encode())
    s.settimeout(secs)
    buf = b""
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            d = s.recv(4096)
            if not d:
                break
            buf += d
    except socket.timeout:
        pass
    except OSError as e:
        buf += ("[err %s]" % e).encode()
    s.close()
    first = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace") if buf else "无响应"
    return first, buf


print("=" * 70)
print("A. 直连 127.0.0.1:3080（后端本身）")
ck = "%s=%s" % (name, val)
first, buf = ws_probe("127.0.0.1", 3080, ck)
print("   状态行 :", first)
print("   6 秒收到: %d 字节" % len(buf))
print("   前 160 字节:", buf[:160])

print()
print("B. 走我的代理 127.0.0.1:3081（后端看到的 Host 会被改写成 127.0.0.1:3080）")
first2, buf2 = ws_probe("127.0.0.1", 3081, ck)
print("   状态行 :", first2)
print("   6 秒收到: %d 字节" % len(buf2))
print("   前 160 字节:", buf2[:160])

print()
print("=" * 70)
if len(buf2) >= len(buf) and len(buf2) > 0:
    print("结论: 两条通道数据流一致 -> WebSocket 没问题，手机端的现象另有原因")
elif len(buf) > 0 and len(buf2) == 0:
    print("结论: 直连有数据、走代理没数据 -> 我的盲转发把 WS 数据流弄坏了")
else:
    print("结论: 两条都没数据（DSH 可能平时不推数据，只在有事件时推）")
    print("      -> 那就要看手机端的会话列表是从哪个接口来的")
