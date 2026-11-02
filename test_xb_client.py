#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_xb_client.py —— 云协同客户端的离线自测

★ 为什么要有这个：
  客户端是 tkinter GUI，手测很麻烦（要开窗口、点按钮）。
  但底层逻辑（发现、HTTP 调用、分块上传、token）都能离线测。
  2026-10-02 那个"扫不到板子"的 bug 就是因为没有这层测试 —— 
  discover() 在【没有板子】的时候也"正常返回空列表"，看起来没坏。

用法:
    python test_xb_client.py              # 只测离线部分
    python test_xb_client.py --board      # 额外测真机（需要板子在线）
"""
import argparse
import math
import os
import socket
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xb_client as X   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", action="store_true", help="额外测真机")
    ap.add_argument("--ip", default="192.168.110.144")
    ap.add_argument("--token", default="u6kCWANi")
    a = ap.parse_args()

    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    print("=" * 72)
    print(" 云协同客户端自测")
    print("=" * 72)

    # ── ① 本机地址枚举（★ 那个 bug 的根源）──
    print()
    print("【1】本机 IPv4 枚举")
    ips = X.local_ipv4_addrs()
    print("   找到: %s" % ips)
    chk(len(ips) > 0, "能枚举出至少一个非环回地址")
    chk(all(not x.startswith("127.") for x in ips), "不含 127.x")
    real = [x for x in ips if x.startswith("192.168.") or x.startswith("10.")]
    chk(len(real) > 0, "含一个真实内网地址", str(real))

    # ── ② 广播目标 ──
    print()
    print("【2】广播目标顺序")
    tg = X.broadcast_targets()
    for t in tg[:5]:
        print("   %s" % t)
    print("   ... 共 %d 个" % len(tg))
    chk(tg[-1] == "255.255.255.255", "受限广播放最后（它最不可靠）")
    chk(any(t.endswith(".255") for t in tg[:-1]), "有子网定向广播")
    # ★ 关键：本机网段的广播应该在【受限广播之前】
    if real:
        seg = ".".join(real[0].split(".")[:3]) + ".255"
        chk(seg in tg, "本机网段 %s 在列表里" % seg)
        chk(tg.index(seg) < tg.index("255.255.255.255"),
            "本机网段排在受限广播之前")

    # ── ③ discover() 的行为（没板子时不该崩）──
    print()
    print("【3】discover() 健壮性")
    try:
        r = X.discover(1.0)
        chk(isinstance(r, list), "返回 list", "拿到 %d 个" % len(r))
    except Exception as e:
        chk(False, "discover 不崩", str(e))

    # ── ④ Board 的 URL 拼装 ──
    print()
    print("【4】Board._url()")
    b = X.Board("1.2.3.4", "tok")
    u = b._url("/info")
    print("   %s" % u)
    chk("1.2.3.4" in u, "含主机")
    chk(":)8768" not in u and ":8768" in u if ":8768" in u else True,
        "端口没写坏")
    chk("token=tok" in u, "带 token")

    # ── ⑤ 断线时的错误处理（不该抛异常出来）──
    print()
    print("【5】连不上时的表现")
    b2 = X.Board("127.0.0.1", "x")   # 本地没有服务
    try:
        r = b2.call("/info", timeout=2)
        chk(isinstance(r, dict), "返回 dict 而不是抛异常",
            "ok=%s" % (r.get("ok") if isinstance(r, dict) else "?"))
        chk(r.get("ok") is False, "ok=False")
    except Exception as e:
        chk(False, "连不上要优雅返回", "%s: %s" % (type(e).__name__, e))

    # ── ⑥ 真机（可选）──
    if a.board:
        print()
        print("【6】真机连通（%s）" % a.ip)
        hits = X.discover(3.0, extra_ips=[a.ip])
        chk(len(hits) > 0, "UDP 能发现板子",
            str([h.get("ip") for h in hits]))
        b3 = X.Board(a.ip, a.token)
        d = b3.call("/info")
        chk(d.get("ok") is True, "/info 通", "温度 %s" % d.get("temperature_c"))
        r = b3.call("/infer", "POST",
                    {"type": "waveform",
                     "data": [int(127 + 120 * math.sin(i * 2 * math.pi * 40 / 4096))
                              for i in range(4096)],
                     "hint": "raw", "api_key": a.token}, timeout=60)
        chk(r.get("ok") is True, "/infer 通",
            "label=%s conf=%s" % (r.get("label"), r.get("confidence")))
        r2 = b3.call("/voice", "POST", {"text": "现在多少度"}, timeout=90)
        chk(bool(r2.get("reply")), "/voice 通",
            str(r2.get("reply"))[:50])

    print()
    print("=" * 72)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题"))
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
