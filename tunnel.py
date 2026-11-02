#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tunnel.py —— 用 cloudflared 开一条公网隧道，把手机入口挂到互联网上

为什么需要它：
  手机热点本身就是那个"局域网"。热点一关，电脑就没有 192.168.10.x 的地址，
  手机用流量时根本找不到电脑。要"在外面用流量也能进"，必须做**内网穿透**：
  电脑主动往外连到 Cloudflare 的边缘节点，手机再从公网那个网址绕回来。
  好处：不需要公网 IP、不需要路由器端口映射、不受运营商 NAT 影响。

它挂的是我们的代理（127.0.0.1:3081），所以**口令门依然生效** ——
公网上的人没有口令只能看到一个输入框。

用法:
    python tunnel.py                 # 快速隧道（随机网址，重启就变）
    python tunnel.py --url-only      # 只把日志里已有的网址读出来
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CF = os.path.join(HERE, "cloudflared.exe")
LOG = os.path.join(HERE, "tunnel.log")
URLFILE = os.path.join(HERE, "tunnel_url.txt")
TARGET = "http://127.0.0.1:3081"

PAT = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def lan_ip():
    """取本机在局域网里的 IPv4（给微信通知里用；取不到就退回 127.0.0.1）

    ★ 2026-10-01 加：原来通知里的局域网网址写死了 192.168.10.17，
      换网络（现在是 192.168.110.21）之后那个地址就是错的。
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))      # 不真发包，只为让内核选出出口网卡
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def read_url():
    try:
        txt = open(LOG, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    hits = PAT.findall(txt)
    return hits[-1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url-only", action="store_true")
    ap.add_argument("--target", default=TARGET)
    a = ap.parse_args()

    if a.url_only:
        u = read_url()
        print(u if u else "日志里还没有网址")
        return

    if not os.path.exists(CF):
        sys.exit("找不到 %s —— 先把 cloudflared 下载好" % CF)

    # 清空旧日志，避免读到上一次的网址
    open(LOG, "w").close()
    try:
        os.remove(URLFILE)
    except OSError:
        pass

    print("启动隧道: %s  ->  %s" % (a.target, CF), flush=True)
    out = open(LOG, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen([CF, "tunnel", "--no-autoupdate",
                          "--url", a.target],
                         stdout=out, stderr=subprocess.STDOUT,
                         cwd=HERE,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    print("cloudflared PID =", p.pid, flush=True)

    # 等网址出现（一般 5~20 秒）
    url = None
    for _ in range(60):
        time.sleep(1)
        url = read_url()
        if url:
            break
        if p.poll() is not None:
            print("cloudflared 提前退出了，看 %s" % LOG, flush=True)
            break

    if url:
        with open(URLFILE, "w", encoding="utf-8") as f:
            f.write(url)
        # ★ 把新网址推到微信（Server酱）—— 快速隧道的网址重启就变，
        #   人在外面看不到电脑上的文件，所以让电脑主动通知。
        try:
            import notify_url
            key = notify_url.load_key()
            if key:
                ok, msg = notify_url.push(
                    key, "系统管家小白 · 手机入口已就绪",
                    "电脑上的公网隧道已启动。\n\n"
                    "**手机点这个就能进（流量也可以）：**\n\n"
                    "%s/?k=xb7k2m9q\n\n"
                    "局域网（手机在同一 WiFi 时更快）：\n"
                    "http://%s:3081/?k=xb7k2m9q\n" % (url, lan_ip()))
                print("[微信推送] %s" % msg, flush=True)
            else:
                print("[微信推送] 没配 key，跳过（python notify_url.py --key SCTxxx）",
                      flush=True)
        except Exception as e:
            print("[微信推送] 失败: %s" % e, flush=True)
        print()
        print("=" * 70)
        print("公网网址:  %s" % url)
        print()
        print("手机（流量也可以）打开:")
        print("    %s/?k=xb7k2m9q" % url)
        print()
        print("打开一次后会记住 30 天，之后直接开 %s/" % url)
        print("=" * 70)
    else:
        print("还没拿到网址，稍后可以运行: python tunnel.py --url-only")
    print("\n隧道在前台运行，Ctrl-C 结束。日志: %s" % LOG, flush=True)
    try:
        p.wait()
    except KeyboardInterrupt:
        p.terminate()


if __name__ == "__main__":
    main()
