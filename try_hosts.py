# -*- coding: utf-8 -*-
"""try_hosts.py —— 对 ARP 表里的每个 IP 试 zynq/123456 登录, 找出板子"""
import sys
import paramiko

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOSTS = sys.argv[1:] or [
    "192.168.10.3", "192.168.10.4", "192.168.10.5", "192.168.10.8",
    "192.168.10.9", "192.168.10.13", "192.168.10.14", "192.168.10.16",
]

for ip in HOSTS:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(ip, username="zynq", password="123456", timeout=4,
                  banner_timeout=4, auth_timeout=4,
                  look_for_keys=False, allow_agent=False)
        i, o, e = c.exec_command("hostname; ip -4 addr show | grep inet", timeout=8)
        print("✅ %s 是板子!" % ip)
        print(o.read().decode(errors="replace"))
    except Exception as ex:
        print("   %-16s %s" % (ip, type(ex).__name__))
    finally:
        try:
            c.close()
        except Exception:
            pass
