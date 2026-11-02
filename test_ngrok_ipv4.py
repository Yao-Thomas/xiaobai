#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ngrok_ipv4.py —— 判断 ngrok 的失败是"IPv6 被掐"还是"整体被墙"

思路：
  A) 强制 IPv4 建 TCP + TLS（SNI 正确）看能不能握手
  B) 强制 IPv6 同样来一次
  如果 A 能通、B 不能 -> 只要让 ngrok 走 IPv4 就行（改 hosts 即可）
  如果 A 也不通       -> 是 SNI/TLS 层面被拦，改 hosts 也没用
"""
import socket
import ssl
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = "connect.ngrok-agent.com"
PORT = 443


def try_family(family, label):
    try:
        infos = socket.getaddrinfo(HOST, PORT, family, socket.SOCK_STREAM)
    except OSError as e:
        print("  %-6s 解析失败: %s" % (label, e))
        return None
    addr = infos[0][4]
    ip = addr[0]
    t0 = time.time()
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(addr)
        tcp = time.time() - t0
    except OSError as e:
        print("  %-6s %-40s TCP 失败(%.2fs): %s" % (label, ip, time.time()-t0, e))
        return False
    # TLS 握手（带正确的 SNI —— 这一步最容易被拦）
    try:
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(s, server_hostname=HOST)
        tls = time.time() - t0
        ver = ss.version()
        ss.close()
        print("  %-6s %-40s TCP %.2fs  TLS %.2fs  %s  -> 通!"
              % (label, ip, tcp, tls, ver))
        return True
    except Exception as e:
        print("  %-6s %-40s TCP %.2fs  TLS 失败: %s" % (label, ip, tcp, e))
        return False


print("目标: %s:%d" % (HOST, PORT))
print()
print("A) 强制 IPv4")
v4 = try_family(socket.AF_INET, "IPv4")
print()
print("B) 强制 IPv6")
v6 = try_family(socket.AF_INET6, "IPv6")
print()
print("=" * 62)
if v4 and not v6:
    print("结论: IPv4 通、IPv6 被掐")
    print("      -> 改 hosts 把 ngrok 域名指向 IPv4 就能解决（需要管理员）")
elif v4 and v6:
    print("结论: 两个都通 —— 那 ngrok 报错可能是间歇性的，重试即可")
elif not v4 and v6:
    print("结论: 只有 IPv6 通（少见）")
else:
    print("结论: 两个都不通 —— ngrok 在你这网络下整体被拦，换方案吧")
    print("      -> 退回 Cloudflare 隧道，或买域名走 Cloudflare 命名隧道")
