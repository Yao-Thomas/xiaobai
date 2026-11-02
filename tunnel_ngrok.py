#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tunnel_ngrok.py —— 用 ngrok 开一条**固定网址**的公网隧道

为什么用它（而不是 Cloudflare 快速隧道）：
  Cloudflare 快速隧道的名字是随机分配的，重启就变，没法固定。
  ngrok 免费账号可以领 1 个**永久固定**的域名，重启电脑也不变。

★★ 关键坑：必须加 --region ap（亚太节点）！
   默认区域会优先走 IPv6（2409:... 是中国移动 IPv6），
   连接会被 RST 掐断，报错长这样：
       wsarecv: An existing connection was forcibly closed by the remote host
   换成亚太节点后就正常了。

★ 另一个坑：免费版**不允许**通过 http/s 代理跑 agent，
   设了 HTTPS_PROXY 会直接报 ERR_NGROK_9009（那是付费功能）。
   所以不要给它设代理环境变量。

用法:
    python tunnel_ngrok.py                          # 随机网址（测试用）
    python tunnel_ngrok.py --domain xxx.ngrok-free.dev   # 固定网址
    python tunnel_ngrok.py --url-only               # 读当前网址
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NGROK = os.path.join(HERE, "ngrok.exe")
LOG = os.path.join(HERE, "ngrok.log")
URLFILE = os.path.join(HERE, "ngrok_url.txt")
TARGET = "3081"
REGION = "ap"          # ★ 必须亚太，否则走 IPv6 被 RST

PAT = re.compile(r"url=(https://[a-z0-9.-]+\.ngrok(?:-free)?\.[a-z]+)")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def read_url():
    try:
        txt = open(LOG, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    hits = PAT.findall(txt)
    return hits[-1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default=None,
                    help="免费领的固定域名，如 xxx.ngrok-free.dev")
    ap.add_argument("--url-only", action="store_true")
    a = ap.parse_args()

    if a.url_only:
        u = read_url()
        print(u if u else "日志里还没有网址")
        return

    if not os.path.exists(NGROK):
        sys.exit("找不到 %s" % NGROK)

    # ★ 绝不能让 ngrok 走代理（免费版不支持，会 ERR_NGROK_9009）
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        env.pop(k, None)

    args = [NGROK, "http", TARGET, "--region", REGION, "--log=stdout"]
    if a.domain:
        args += ["--domain", a.domain]
    args += ["--log-format", "logfmt"]

    open(LOG, "w").close()
    try:
        os.remove(URLFILE)
    except OSError:
        pass

    print("启动 ngrok: %s  (region=%s%s)"
          % (TARGET, REGION, ", domain=" + a.domain if a.domain else ""),
          flush=True)
    out = open(LOG, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, cwd=HERE,
                         env=env,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    print("ngrok PID =", p.pid, flush=True)

    url = None
    for _ in range(45):
        time.sleep(1)
        url = read_url()
        if url:
            break
        if p.poll() is not None:
            print("ngrok 退出了，看 %s" % LOG, flush=True)
            break

    if url:
        with open(URLFILE, "w", encoding="utf-8") as f:
            f.write(url)
        print()
        print("=" * 72)
        print("公网网址:  %s" % url)
        print()
        print("手机（流量也可以）打开:")
        print("    %s/?k=xb7k2m9q" % url)
        if not a.domain:
            print()
            print("注意: 这是随机网址，重启会变。")
            print("      去 https://dashboard.ngrok.com/domains 领一个免费固定域名，")
            print("      然后加上 --domain 参数重启，才是永久的。")
        print("=" * 72)
    else:
        print("还没拿到网址，稍后: python tunnel_ngrok.py --url-only")
    print("\n隧道在前台运行，Ctrl-C 结束。日志: %s" % LOG, flush=True)

    try:
        p.wait()
    except KeyboardInterrupt:
        p.terminate()


if __name__ == "__main__":
    main()
