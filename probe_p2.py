#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_p2.py —— P2 前置勘察: 天气 API 能不能通 + 无线信号从哪读"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 工具"
for t in wget curl python3 iw iwconfig; do printf "%-10s " $t; command -v $t || echo "(无)"; done
echo
echo "### DNS"
cat /etc/resolv.conf 2>&1 | head -5
getent hosts www.baidu.com 2>&1 | head -2
echo
echo "### CA 证书"
ls /etc/ssl/certs/ca-certificates.crt 2>&1
python3 -c "import ssl;print('ssl ok', ssl.OPENSSL_VERSION)" 2>&1
echo
echo "### 试 http (wttr.in)"
timeout 20 wget -q -T 12 -O - "http://wttr.in/Beijing?format=%t+%C+%h" 2>&1 | head -3
echo
echo "### 试 https (wttr.in)"
timeout 20 wget -q -T 12 -O - "https://wttr.in/Beijing?format=%t+%C" 2>&1 | head -3
echo
echo "### 试 open-meteo (https)"
timeout 20 wget -q -T 12 -O - "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&current=temperature_2m,weather_code" 2>&1 | head -3
echo
echo "### python3 urllib https 能否用"
python3 - <<'PY'
import ssl, urllib.request
for url in ("http://wttr.in/Beijing?format=j1",
            "https://api.open-meteo.com/v1/forecast?latitude=39.9&longitude=116.4&current=temperature_2m"):
    try:
        r = urllib.request.urlopen(url, timeout=12)
        d = r.read(200)
        print("OK  ", url[:60], r.status, d[:80])
    except Exception as e:
        print("FAIL", url[:60], type(e).__name__, e)
PY
echo
echo "### 无线信号相关"
echo "--- /proc/net/wireless ---"; cat /proc/net/wireless 2>&1
echo "--- /sys/class/net/wl*/ ---"; ls /sys/class/net/ | grep wl
for f in /sys/class/net/wl*/operstate /sys/class/net/wl*/address; do printf "%s = " $f; cat $f 2>&1; done
echo "--- iw dev ---"; iw dev 2>&1 | head -20
echo "--- iwconfig ---"; iwconfig 2>&1 | head -12
echo "--- /proc/net/wireless 原始 ---"; od -c /proc/net/wireless 2>/dev/null | head -8
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)


main()
