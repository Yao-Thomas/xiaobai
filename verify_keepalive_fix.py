#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_keepalive_fix.py —— 验证 keep-alive 那个 403 的修复

背景：代理原来只改写"每条连接的第一个请求头"，之后盲转发。
浏览器 keep-alive 复用连接时，第 2 个请求带着原始 Host 过去 -> DSH 返回
    403 gateway/internal
现象是"网页能开、静态资源 200、但发消息 /api/session/prompt 403"。

修法：非 WebSocket 请求强制 Connection: close，逼浏览器每请求开新连接。
这里验证三件事：
  1) 非升级请求的响应里必须是 Connection: close（否则复用还会发生）
  2) 真的 POST 一个 /api 接口（带手机那种 Host/Origin），必须是 200 不是 403
  3) WebSocket 升级仍然要 101（别被 Connection: close 弄坏）
"""
import base64
import http.cookiejar
import os
import socket
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from dsh_proxy import load_secret, make_auth_cookie          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROXY = ("127.0.0.1", 3081)
PHONE_HOST = "192.168.10.17:3081"          # 手机看到的 Host / Origin

secret = load_secret()
name, val = make_auth_cookie(secret)
COOKIE = "%s=%s; dshgate=xb7k2m9q" % (name, val)

ok = []

# ---------------- 1) 响应里有没有 Connection: close ----------------
print("1) 非升级请求的响应是否强制 close（防止浏览器复用连接）")
s = socket.create_connection(PROXY, timeout=8)
s.sendall(("GET / HTTP/1.1\r\nHost: %s\r\nCookie: %s\r\n"
           "Connection: keep-alive\r\n\r\n"
           % (PHONE_HOST, COOKIE)).encode())
s.settimeout(8)
buf = b""
try:
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d:
            break
        buf += d
except socket.timeout:
    pass
s.close()
hdrs = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
line = hdrs.split("\r\n")[0]
conn = [h for h in hdrs.split("\r\n") if h.lower().startswith("connection:")]
print("   状态行  :", line)
print("   Connection 头:", conn)
if "200" in line and any("close" in c.lower() for c in conn):
    print("   [OK] 后端被要求 close -> 浏览器不会再复用连接")
    ok.append(True)
else:
    print("   [X] 没有 close，复用还会发生")
    ok.append(False)

# ---------------- 2) 真打一个 /api 接口 ----------------
print()
print("2) 用手机那种 Host/Origin 打真实 /api 接口（期望 200，不是 403）")
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
try:
    op.open("http://127.0.0.1:3081/?k=xb7k2m9q", timeout=6)
except Exception as e:
    print("   拿 cookie 失败:", e)

for path in ("/api/skills/list", "/api/agentPresets/list",
             "/api/dynamicCordisRunner/inventory"):
    req = urllib.request.Request("http://127.0.0.1:3081" + path,
                                 data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Origin", "http://" + PHONE_HOST)      # 手机浏览器会带这个
    try:
        r = op.open(req, timeout=15)
        print("   %-38s -> %s" % (path, r.status))
        ok.append(r.status == 200)
    except urllib.error.HTTPError as e:
        body = e.read(120).decode("utf-8", "replace")
        print("   %-38s -> %s  %s" % (path, e.code, body))
        ok.append(False)
    except Exception as e:
        print("   %-38s -> 异常 %s" % (path, e))
        ok.append(False)

# ---------------- 3) WebSocket 还能不能 101 ----------------
print()
print("3) WebSocket 升级不能被 Connection: close 弄坏（期望 101）")
key = base64.b64encode(os.urandom(16)).decode()
s = socket.create_connection(PROXY, timeout=8)
s.sendall(("GET /api/remote.mux HTTP/1.1\r\nHost: %s\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
           "Origin: http://%s\r\nCookie: %s\r\n\r\n"
           % (PHONE_HOST, key, PHONE_HOST, COOKIE)).encode())
s.settimeout(6)
first = b""
try:
    first = s.recv(200)
except socket.timeout:
    pass
line3 = first.split(b"\r\n", 1)[0].decode("latin-1", "replace")
print("   状态行:", line3)
ok.append("101" in line3)
s.close()

print()
print("=" * 66)
print("结果: %d/%d 项通过" % (sum(1 for x in ok if x), len(ok)))
print("全部通过 -> 手机上重新打开页面即可" if all(ok)
      else "还有没过的，看上面哪一项是 [X]")
