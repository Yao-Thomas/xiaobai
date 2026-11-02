#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_public.py —— 从公网网址验证整条链路（模拟手机用流量访问）

测试顺序：
  1) 不带口令  -> 应该看到"需要口令"页（403），证明公网上没裸奔
  2) 带口令    -> 303 并下发 cookie
  3) 用 cookie -> 200 拿到 DSH 页面
  4) 打一个真实 /api 接口 -> 200（不是 403）
"""
import sys
import http.cookiejar
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

URL = sys.argv[1] if len(sys.argv) > 1 else \
    open("tunnel_url.txt", encoding="utf-8").read().strip()
TOKEN = "xb7k2m9q"
print("公网网址:", URL)
print()

ok = []

# 1) 不带口令
print("1) 不带口令访问（期望 403 + 口令页）")
try:
    r = urllib.request.urlopen(URL + "/", timeout=25)
    body = r.read(200).decode("utf-8", "replace")
    print("   ->", r.status, "（意外：居然直接进去了）")
    ok.append(False)
except urllib.error.HTTPError as e:
    body = e.read(300).decode("utf-8", "replace")
    print("   ->", e.code, "|", body[:60].replace("\n", " "))
    ok.append(e.code == 403 and "口令" in body)
except Exception as e:
    print("   -> 异常:", e)
    ok.append(False)

# 2)+3) 带口令 -> cookie -> 首页
print()
print("2) 带口令拿 cookie，再请求首页")
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
try:
    op.open("%s/?k=%s" % (URL, TOKEN), timeout=25)
    names = [c.name[:26] for c in cj]
    print("   拿到的 cookie:", names)
    ok.append(len(names) >= 2)
    r = op.open(URL + "/", timeout=30)
    body = r.read()
    print("   首页 ->", r.status, len(body), "字节")
    ok.append(r.status == 200 and len(body) > 5000)
except Exception as e:
    print("   异常:", e)
    ok.append(False)
    ok.append(False)

# 4) 真实 API
print()
print("3) 打真实 /api 接口（期望 200，手机发消息走的就是这类）")
for path in ("/api/skills/list", "/api/agentPresets/list"):
    req = urllib.request.Request(URL + path, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        r = op.open(req, timeout=30)
        print("   %-28s -> %s" % (path, r.status))
        ok.append(r.status == 200)
    except urllib.error.HTTPError as e:
        print("   %-28s -> %s %s" % (path, e.code,
                                     e.read(90).decode("utf-8", "replace")))
        ok.append(False)
    except Exception as e:
        print("   %-28s -> 异常 %s" % (path, e))
        ok.append(False)

print()
print("=" * 62)
print("结果: %d/%d 项通过" % (sum(1 for x in ok if x), len(ok)))
if all(ok):
    print()
    print("★ 公网入口可用。手机用流量打开:")
    print("    %s/?k=%s" % (URL, TOKEN))
