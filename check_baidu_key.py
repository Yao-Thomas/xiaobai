#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_baidu_key.py —— 检查手上的百度密钥格式，并实测能不能换 token

百度语音的正确格式：
    API Key     : 24 个字符
    Secret Key  : 32 个字符

换 token 的接口：
    POST https://aip.baidubce.com/oauth/2.0/token
         grant_type=client_credentials&client_id=<APIKey>&client_secret=<SecretKey>
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- 找到工程里现在用的 key ----
CANDIDATES = [
    ("D:/ubuntu_iso/agent/config.py", None),
    ("D:/ubuntu_iso/agent/tts.py", None),
]

found = {}
for path, _ in CANDIDATES:
    if not os.path.exists(path):
        continue
    txt = open(path, encoding="utf-8", errors="replace").read()
    for m in re.finditer(
            r'(?i)(baidu[_a-z]*api[_a-z]*key|api_key|ak)\s*[:=]\s*["\']([^"\']+)["\']',
            txt):
        found.setdefault("api_key", []).append((path, m.group(2)))
    for m in re.finditer(
            r'(?i)(baidu[_a-z]*secret[_a-z]*key|secret_key|sk)\s*[:=]\s*["\']([^"\']+)["\']',
            txt):
        found.setdefault("secret_key", []).append((path, m.group(2)))

print("=" * 74)
print("1) 工程里现在用的密钥")
print("=" * 74)
if not found:
    print("  没在 config.py / tts.py 里找到")
for kind, items in found.items():
    for path, val in items:
        print("  %-11s %-22s 长度=%-3d  %s"
              % (kind, os.path.basename(path), len(val),
                 val[:6] + "..." + val[-4:] if len(val) > 12 else val))

ak = (found.get("api_key") or [(None, None)])[0][1]
sk = (found.get("secret_key") or [(None, None)])[0][1]

print()
print("=" * 74)
print("2) 格式核对（正确应为 API Key 24 字符 / Secret Key 32 字符）")
print("=" * 74)
if ak:
    print("  API Key    %d 字符  %s" % (len(ak), "OK" if len(ak) == 24 else "✗ 不对"))
if sk:
    print("  Secret Key %d 字符  %s" % (len(sk), "OK" if len(sk) == 32 else "✗ 不对"))

print()
print("=" * 74)
print("3) 实测换 token（能换到就说明密钥有效）")
print("=" * 74)
if not (ak and sk):
    print("  缺 key，跳过")
    sys.exit(0)
url = "https://aip.baidubce.com/oauth/2.0/token?" + urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": ak, "client_secret": sk})
try:
    with urllib.request.urlopen(url, timeout=20) as r:
        j = json.loads(r.read().decode())
    if "access_token" in j:
        print("  ✓ 换到了 access_token（前 20 字符）:",
              j["access_token"][:20], "...")
        print("     有效期: %s 秒" % j.get("expires_in"))
        print()
        print("  ★ 密钥有效！可以直接用来做语音识别/合成")
    else:
        print("  ✗ 失败:", json.dumps(j, ensure_ascii=False)[:300])
except Exception as e:
    print("  ✗ 请求异常:", e)
    print("     （如果板子/电脑上不了百度，可能是网络问题）")
