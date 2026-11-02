#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""netscan.py —— 扫 192.168.10.0/24 的 22 端口, 找板子"""
import socket
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FOUND = []
LOCK = threading.Lock()


def probe(ip):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        if s.connect_ex((ip, 22)) == 0:
            with LOCK:
                FOUND.append(ip)
    except Exception:
        pass
    finally:
        s.close()


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "192.168.10."
    ths = []
    for i in range(1, 255):
        t = threading.Thread(target=probe, args=(base + str(i),))
        t.daemon = True
        t.start()
        ths.append(t)
        if len(ths) >= 64:
            for t in ths:
                t.join(timeout=1.0)
            ths = []
    for t in ths:
        t.join(timeout=1.0)
    print("扫 %s0/24 : 开放 22 端口的主机 = %s"
          % (base, sorted(FOUND, key=lambda x: int(x.split(".")[-1])) or "无"))


main()
