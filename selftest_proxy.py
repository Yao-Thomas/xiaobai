#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest_proxy.py —— 验证"自签 cookie 能不能通过 DSH 认证"

不需要启动代理，直接：
  1. 从 ~/.dsh/.credentials.yaml 读 secret
  2. 按 DSH 的格式自签一个 cookie
  3. 带着它请求 http://127.0.0.1:3080/，看是不是 200（不带时是 401）
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from dsh_proxy import load_secret, make_auth_cookie     # noqa: E402

print("1) 读 secret ...")
s = load_secret()
print("   secret 长度 =", len(s))

print("2) 自签 cookie ...")
name, val = make_auth_cookie(s)
print("   cookie 名 =", name)
print("   值前 40 字符 =", val[:40], "...")

print("3) 不带 cookie 请求 / （预期 401）")
try:
    r = urllib.request.urlopen("http://127.0.0.1:3080/", timeout=6)
    print("   ->", r.status, "（意外，竟然是通的）")
except urllib.error.HTTPError as e:
    print("   ->", e.code, e.read()[:80].decode("utf-8", "replace"))

print("4) 带上自签 cookie 请求 / （期望 200）")
req = urllib.request.Request("http://127.0.0.1:3080/")
req.add_header("Cookie", "%s=%s" % (name, val))
try:
    r = urllib.request.urlopen(req, timeout=8)
    body = r.read(400)
    print("   ->", r.status, r.headers.get("Content-Type"))
    print("   页面开头:", body[:120].decode("utf-8", "replace").replace("\n", " "))
    print()
    print("   [OK] 成功：自签 cookie 被 DSH 接受，手机入口可行")
except urllib.error.HTTPError as e:
    print("   ->", e.code, e.read()[:200].decode("utf-8", "replace"))
    print()
    print("   [X] 失败：还需要别的凭据")
