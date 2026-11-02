# -*- coding: utf-8 -*-
"""find_board.py —— 扫描局域网里开 22 端口的主机, 并识别哪个是 Zynq 板"""
import socket
import concurrent.futures

SUBNETS = ["192.168.10.", "192.168.43.", "192.168.1."]


def probe(ip):
    s = socket.socket()
    s.settimeout(0.45)
    try:
        s.connect((ip, 22))
        banner = ""
        try:
            s.settimeout(0.6)
            banner = s.recv(64).decode("utf-8", "ignore").strip()
        except Exception:
            pass
        return (ip, banner)
    except Exception:
        return None
    finally:
        s.close()


targets = [p + str(i) for p in SUBNETS for i in range(1, 255)]
found = []
with concurrent.futures.ThreadPoolExecutor(max_workers=128) as ex:
    for r in ex.map(probe, targets):
        if r:
            found.append(r)

print("开放 22 端口的主机:")
for ip, b in sorted(found):
    print("  %-16s %s" % (ip, b))
if not found:
    print("  (无)")
