# -*- coding: utf-8 -*-
"""val_scan.py —— 验证扫描器本身工作正常: 去扫已知在线的设备(路由器等)"""
import socket
import concurrent.futures

TARGETS = ["192.168.10.1", "192.168.10.3", "192.168.10.4", "192.168.10.5",
           "192.168.10.8", "192.168.10.9", "192.168.10.13", "192.168.10.14",
           "192.168.10.16", "192.168.10.17"]
PORTS = [22, 80, 443, 8080, 53]


def probe(args):
    ip, port = args
    s = socket.socket()
    s.settimeout(1.2)
    try:
        s.connect((ip, port))
        return (ip, port, True)
    except Exception:
        return (ip, port, False)
    finally:
        s.close()


jobs = [(ip, p) for ip in TARGETS for p in PORTS]
print("扫描 %d 个目标 x %d 个端口 ..." % (len(TARGETS), len(PORTS)))
found = []
with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
    for ip, port, ok in ex.map(probe, jobs):
        if ok:
            found.append((ip, port))

print("\n开放的端口:")
for ip, port in sorted(found):
    print("   %-16s :%d" % (ip, port))
if not found:
    print("   (一个都没有 —— 连路由器都没扫到, 说明是扫描方式/网络隔离的问题)")

# 顺便看一下本机能路由到哪些网段
print("\n本机路由表:")
import subprocess
try:
    out = subprocess.check_output(["route", "print", "-4"], text=True, errors="replace")
    for line in out.splitlines():
        if "192.168" in line or "0.0.0.0" in line:
            print("   " + line.strip())
except Exception as e:
    print("   ", e)
