#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_cloud_from_pc.py —— ★ 从 PC 侧诊断云协同连不上

用户反馈："云协同好像也连不上"。
这个脚本从 PC 出发，逐层排查到底是哪一段不通：
    ① UDP 广播发现（8769）—— 客户端"扫一扫找板子"用的
    ② TCP 端口（8768）
    ③ GET /health（不需要认证）
    ④ GET /info（带 token）
    ⑤ POST /infer（推理契约）
    ⑥ POST /voice（转发给 agent）

用法:
    python check_cloud_from_pc.py
    python check_cloud_from_pc.py --ip 192.168.110.144 --token xxxx
"""
import argparse
import json
import math
import socket
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK = "\u2713"
NO = "\u2717"


def hdr(s):
    print()
    print("-" * 72)
    print(" %s" % s)
    print("-" * 72)


def http(method, url, body=None, timeout=10):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return {"code": r.status, "body": raw,
                    "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        return {"code": e.code, "body": e.read().decode("utf-8", "replace"),
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"code": 0, "body": "%s: %s" % (type(e).__name__, e),
                "ms": int((time.time() - t0) * 1000)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.110.144")
    ap.add_argument("--token", default="")
    ap.add_argument("--port", type=int, default=8768)
    a = ap.parse_args()
    base = "http://%s:%d" % (a.ip, a.port)

    print("=" * 72)
    print(" 云协同连通性诊断（从 PC 侧）")
    print("=" * 72)
    print(" 板子: %s  端口: %d" % (a.ip, a.port))

    results = []

    # ── ① UDP 发现 ──
    hdr("① UDP 广播发现（8769）—— 客户端「扫一扫找板子」用的")
    found = None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(3)
    try:
        s.sendto(b"XIAOBAI_DISCOVER", ("255.255.255.255", 8769))
        d, addr = s.recvfrom(2048)
        found = d.decode("utf-8", "replace")
        print("   %s 收到响应 from %s" % (OK, addr))
        print("     %s" % found[:300])
        results.append(("UDP 发现", True))
    except Exception as e:
        print("   %s 没收到广播响应: %s" % (NO, e))
        print("     （★ 很常见：很多路由器/AP 默认【不透传广播】）")
        # 退而求其次：单播问一次
        try:
            s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s2.settimeout(3)
            s2.sendto(b"XIAOBAI_DISCOVER", (a.ip, 8769))
            d, addr = s2.recvfrom(2048)
            print("   %s 但【单播】收到了 from %s" % (OK, addr))
            print("     %s" % d.decode("utf-8", "replace")[:300])
            results.append(("UDP 发现(单播)", True))
            print("     ⇒ ★ 结论：板子在听，只是广播被路由器挡了")
            print("        客户端应该支持「手动填 IP」或改用单播探测")
        except Exception as e2:
            print("   %s 单播也没响应: %s" % (NO, e2))
            results.append(("UDP 发现(单播)", False))
    finally:
        s.close()

    # ── ② TCP ──
    hdr("② TCP 端口")
    t0 = time.time()
    try:
        c = socket.create_connection((a.ip, a.port), timeout=5)
        c.close()
        print("   %s %s:%d 可连接（%.0f ms）"
              % (OK, a.ip, a.port, (time.time() - t0) * 1000))
        results.append(("TCP", True))
    except Exception as e:
        print("   %s 连不上: %s" % (NO, e))
        results.append(("TCP", False))

    # ── ③ /health ──
    hdr("③ GET /health（不需要认证）")
    r = http("GET", base + "/health")
    print("   HTTP %s  %d ms" % (r["code"], r["ms"]))
    print("   %s" % r["body"][:300])
    results.append(("/health", r["code"] == 200))

    # ── ④ /info ──
    hdr("④ GET /info（带 token）")
    if not a.token:
        print("   （没给 --token，跳过）")
        print("   ★ 板子上的 token 在 /etc/xiaobai-cloud.json")
    else:
        r = http("GET", base + "/info?token=" + a.token)
        print("   HTTP %s  %d ms" % (r["code"], r["ms"]))
        print("   %s" % r["body"][:400])
        results.append(("/info", r["code"] == 200))

    # ── ⑤ /infer ──
    hdr("⑤ POST /infer（推理契约）")
    if a.token:
        data = [int(127 + 120 * math.sin(i * 2 * math.pi * 40 / 4096))
                for i in range(4096)]
        r = http("POST", base + "/infer",
                 {"type": "waveform", "data": data, "hint": "raw",
                  "api_key": a.token}, timeout=60)
        print("   HTTP %s  %d ms" % (r["code"], r["ms"]))
        try:
            d = json.loads(r["body"])
            print("   ok=%s label=%s conf=%s elapsed_ms=%s"
                  % (d.get("ok"), d.get("label"), d.get("confidence"),
                     d.get("elapsed_ms")))
            print("   engine=%s" % (d.get("detail", {}).get("engine")))
            results.append(("/infer", bool(d.get("ok"))))
        except Exception:
            print("   %s" % r["body"][:300])
            results.append(("/infer", False))
    else:
        print("   （没给 --token，跳过）")

    # ── ⑥ /voice ──
    hdr("⑥ POST /voice（转发给 agent）")
    if a.token:
        r = http("POST", base + "/voice?token=" + a.token,
                 {"text": "现在多少度"}, timeout=90)
        print("   HTTP %s  %d ms" % (r["code"], r["ms"]))
        print("   %s" % r["body"][:300])
        results.append(("/voice", r["code"] == 200))
    else:
        print("   （没给 --token，跳过）")

    # ── 汇总 ──
    print()
    print("=" * 72)
    for name, ok in results:
        print("   %s %s" % (OK if ok else NO, name))
    bad = [n for n, ok in results if not ok]
    print()
    if not bad:
        print(" 总体: ★ 全部通过 —— 云协同是通的")
    else:
        print(" 总体: ★ 有 %d 项不通: %s" % (len(bad), bad))
    print("=" * 72)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
