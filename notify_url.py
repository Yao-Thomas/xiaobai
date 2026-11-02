#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_url.py —— 把当前公网网址推送到微信（Server酱）

为什么需要它：
  Cloudflare 快速隧道的网址**每次重启都会变**。
  变了以后你在外面看不到电脑上的 tunnel_url.txt，
  所以让电脑**主动把新网址推到你微信**，手机上随时能查到。

用法:
    python notify_url.py --key SCTxxxxxxxx        # 推一次
    python notify_url.py --key SCTxxxxxxxx --test # 测试推送

Server酱怎么拿 key（免费）：
    1. 打开 https://sct.ftqq.com
    2. 用微信扫码登录
    3. 复制页面上的 SendKey（形如 SCT123456...）
    4. 用它调用本脚本

配置也可以写进 notify_key.txt（一行，只放 key），
这样开机自启时不用在命令行里带 key。
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URLFILE = os.path.join(HERE, "tunnel_url.txt")
KEYFILE = os.path.join(HERE, "notify_key.txt")
API = "https://sctapi.ftqq.com/%s.send"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_key(explicit=None):
    if explicit:
        return explicit.strip()
    if os.path.exists(KEYFILE):
        return open(KEYFILE, encoding="utf-8").read().strip()
    return None


def load_url():
    if not os.path.exists(URLFILE):
        return None
    u = open(URLFILE, encoding="utf-8").read().strip()
    return u or None


def push(key, title, body):
    """Server酱推送。返回 (ok, 说明)"""
    data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
    req = urllib.request.Request(API % key, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt)
        except Exception:
            return (r.status == 200), txt[:200]
        if j.get("code") == 0:
            return True, "已推送到微信"
        return False, "Server酱返回: %s" % txt[:200]
    except Exception as e:
        return False, "推送失败: %s" % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None, help="Server酱 SendKey")
    ap.add_argument("--test", action="store_true", help="发一条测试消息")
    ap.add_argument("--url", default=None, help="手动指定网址（默认读 tunnel_url.txt）")
    a = ap.parse_args()

    key = load_key(a.key)
    if not key:
        sys.exit("没有 key。先运行一次: python notify_url.py --key SCTxxxxx\n"
                 "（会把 key 存到 notify_key.txt，之后自启就不用带了）")

    # 首次带 key 调用 -> 落盘，方便开机自启用
    if a.key and not os.path.exists(KEYFILE):
        with open(KEYFILE, "w", encoding="utf-8") as f:
            f.write(a.key.strip())
        print("key 已保存到", KEYFILE)

    if a.test:
        ok, msg = push(key, "系统管家小白 · 推送测试",
                       "如果你看到这条，说明网址推送已经配好了。\n\n"
                       "以后隧道每次启动，新的网址会自动发到这里。")
        print(msg)
        sys.exit(0 if ok else 1)

    url = a.url or load_url()
    if not url:
        sys.exit("读不到 tunnel_url.txt —— 隧道可能还没起来")

    full = "%s/?k=xb7k2m9q" % url
    body = ("电脑上的公网隧道已启动。\n\n"
            "**手机点这个就能进（流量也可以）：**\n\n"
            "%s\n\n"
            "局域网（手机开着热点时更快）：\n"
            "http://192.168.10.17:3081/?k=xb7k2m9q\n\n"
            "打开一次会记住 30 天，之后直接开 %s/\n" % (full, url))
    ok, msg = push(key, "系统管家小白 · 手机入口已就绪", body)
    print(msg, "|", full)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
