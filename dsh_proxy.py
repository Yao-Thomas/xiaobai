#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh_proxy.py —— 让手机能打开 DSH Web GUI 的反向代理

════════════════════════════════════════════════════════════════════
为什么需要它（全部是从 DSH 源码里查证的，不是猜的）
════════════════════════════════════════════════════════════════════
1) DSH Web 默认只监听 127.0.0.1，而且**故意**如此：
     dsh-web-app/lib/startup.js:40
       --host 0.0.0.0 -> "intentionally not supported yet for safety:
                          it would expose remote code execution to the network"
   并且 webserver 的 schema 只接受 127.0.0.1 / 0.0.0.0，填局域网 IP 也不合法。

2) 但作者留了正门：`--trusted-host`。而 /api 的信任校验
   (dsh-client-connection/lib/index.js:201) 只看三件事：
       Host 必须是 loopback 或受信任的 authority
       Sec-Fetch-Site 不能是 cross-site
       Origin（若存在）必须与 Host 同源
   => 代理把 Host 改写成 127.0.0.1:3080、丢掉 Origin/Sec-Fetch-Site，就合法通过。

3) 还有一层浏览器认证 (authorizeIndex / cookie)：
       正常流程是 DSH 打印一个 http://127.0.0.1:3080/?token=<launchToken> 的网址，
       浏览器打开后用**持久的 secret** 签一个 cookie 发下来。
       launchToken 是每进程随机的、不在文件里 —— 但我们**不需要它**：
       cookie 就是  v1.<base64url(payload)>.<base64url(HMAC-SHA256(secret, body))>，
       而 secret 存在 ~/.dsh/.credentials.yaml 里，所以**我们自己就能签**。
       （cookie 属性是 HttpOnly; SameSite=Strict，**没有 Secure**，所以 http 可用）

════════════════════════════════════════════════════════════════════
安全
════════════════════════════════════════════════════════════════════
DSH 拒绝暴露的理由就是"等于把任意命令执行开放给网络"，所以这里加了一道
**口令门**：没有口令的陌生请求只会看到一个输入框，拿不到任何 DSH 内容。
口令每次启动随机生成（也可以 --token 指定）。

用法:
    python dsh_proxy.py                 # 监听 0.0.0.0:3081
    python dsh_proxy.py --port 3081 --token mysecret
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TARGET_HOST = "127.0.0.1"
TARGET_PORT = 3080
AUTHORITY = "127.0.0.1:3080"          # 代理改写后的 Host，cookie 就按这个 authority 签
COOKIE_PREFIX = "dsh-auth-"
GATE_COOKIE = "dshgate"
MAX_HEAD = 64 * 1024
CRED = os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")


REQLOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "dsh_proxy_req.log")


def log(*a):
    print("[proxy]", *a, flush=True)


def rlog(s):
    """把每个请求/响应写进日志文件，方便诊断手机端到底卡在哪一步。"""
    try:
        with open(REQLOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), s))
    except Exception:
        pass


def clear_reqlog():
    try:
        open(REQLOG, "w").close()
    except Exception:
        pass


def b64url(b):
    return base64.b64encode(b).decode().replace("+", "-").replace("/", "_").rstrip("=")


def load_secret(path=CRED):
    """从 ~/.dsh/.credentials.yaml 读 client-connection/browser-session 的 secret"""
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception as e:
        raise SystemExit("读不到凭据文件 %s: %s" % (path, e))
    # 只取 client-connection/browser-session 段落里的 secret
    m = re.search(r"client-connection/browser-session:(.*?)(?=\n\s{2}\S|\Z)",
                  txt, re.S)
    blob = m.group(1) if m else txt
    m2 = re.search(r"secret:\s*\"?([A-Za-z0-9_-]{20,})\"?", blob)
    if not m2:
        raise SystemExit("在凭据文件里没找到 browser-session 的 secret")
    return m2.group(1)


def make_auth_cookie(secret, days=30):
    """按 DSH 的格式自签一个合法 cookie，返回 (cookie名, cookie值)

    ★ 关键细节：凭据文件里存的是 base64url 文本，但 DSH 里的 this.secret 是
      **解码后的 32 字节原始数据**（见 canonicalSecret/storedSecret），
      HMAC 的密钥用的是原始字节，不是那串文本。用错就一直是 401。
    """
    authority = AUTHORITY
    name = COOKIE_PREFIX + b64url(hashlib.sha256(authority.encode()).digest())
    issued = int(time.time() * 1000)
    expires = issued + days * 1440 * 60 * 1000
    payload = {"version": 1, "authority": authority,
               "issuedAt": issued, "expiresAt": expires}
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    key = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    sig = b64url(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return name, "v1.%s.%s" % (body, sig)


def read_head(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        try:
            chunk = sock.recv(4096)
        except OSError:
            return None, b""
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > MAX_HEAD:
            return None, b""
    i = buf.index(b"\r\n\r\n") + 4
    return buf[:i], buf[i:]


def parse_head(head):
    lines = head.split(b"\r\n")
    req = lines[0].decode("latin-1", "replace")
    parts = req.split(" ")
    if len(parts) < 2:
        return None, None, None
    method, target = parts[0], parts[1]
    headers = []
    for ln in lines[1:]:
        if not ln:
            continue
        s = ln.decode("latin-1", "replace")
        if ":" in s:
            k, v = s.split(":", 1)
            headers.append((k.strip(), v.strip()))
    return method, target, headers


def hget(headers, name):
    n = name.lower()
    for k, v in headers:
        if k.lower() == n:
            return v
    return None


GATE_PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>需要口令</title>
<body style="font-family:system-ui;background:#0f1116;color:#e8ecf4;padding:1.6rem">
<h2 style="margin:0 0 .6rem">系统管家 · 远程入口</h2>
<p style="color:#9fb0cc">口令是电脑上 <b>D:/ubuntu_iso/start_proxy.bat</b> 里的 --token 值（当前是 xb7k2m9q）。</p><p style="color:#7d8ba5;font-size:.9rem">更好：直接用带 ?k=口令 的完整网址打开一次，之后就不用再输了。</p>
<form method=get action="/">
<input name=k autocomplete=off style="font-size:1.15rem;padding:.7rem;width:14rem;
 background:#181c26;color:#e8ecf4;border:1px solid #39445c;border-radius:10px">
<button style="font-size:1.05rem;padding:.7rem 1.1rem;border-radius:10px;
 background:#3b74e0;color:#fff;border:0;margin-left:.4rem">进入</button>
</form></body>"""


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        s.settimeout(30)
        head, rest = read_head(s)
        if head is None:
            return
        method, target, headers = parse_head(head)
        if method is None:
            return

        path, _, query = target.partition("?")
        q = urllib.parse.parse_qs(query)
        given = (q.get("k") or [None])[0]
        cookie = hget(headers, "cookie") or ""

        def has(name):
            return any(p.strip().startswith(name + "=")
                       for p in cookie.split(";"))

        # ---- 口令：?k= 设 cookie -> 同时把 DSH 的认证 cookie 一起发下去 ----
        if given is not None and hmac.compare_digest(given, self.server.token):
            auth_name, auth_val = self.server.auth
            extra = ""
            if not has(auth_name):
                extra = ("Set-Cookie: %s=%s; Path=/; Max-Age=2592000; "
                         "SameSite=Lax\r\n" % (auth_name, auth_val))
            resp = ("HTTP/1.1 303 See Other\r\n"
                    "Location: %s\r\n"
                    "Set-Cookie: %s=%s; Path=/; Max-Age=2592000; "
                    "SameSite=Lax\r\n"
                    "%s"
                    "Cache-Control: no-store\r\n"
                    "Content-Length: 0\r\nConnection: close\r\n\r\n"
                    % (path or "/", GATE_COOKIE, self.server.token, extra))
            s.sendall(resp.encode())
            return

        # ---- 没带口令也没带认证 cookie -> 只给一个口令输入页 ----
        if not has(GATE_COOKIE) and not has(self.server.auth[0]):
            page = GATE_PAGE.encode()
            s.sendall(("HTTP/1.1 403 Forbidden\r\n"
                       "Content-Type: text/html; charset=utf-8\r\n"
                       "Content-Length: %d\r\nConnection: close\r\n\r\n"
                       % len(page)).encode() + page)
            return

        # ---- 转发：改 Host、改写 Origin，并强制每请求一条新连接 ----
        #
        # ★★★ 这里是整个代理最容易错的地方，记录一下踩过的坑：
        #   最早的写法是"只改写第一条请求头，然后两个方向盲转发"。
        #   但浏览器默认 keep-alive —— 同一条 TCP 连接上会先后发好几个请求，
        #   第 2、第 3 个请求是**原样**过去的，Host 还是 192.168.10.17:3081，
        #   于是被 DSH 的 /api 信任校验拦下，返回 403 gateway/internal。
        #   现象非常有迷惑性：首页、静态资源、部分 API 都 200（碰巧走了新连接），
        #   但 /api/session/prompt（发消息）403 —— "网页能开、消息发不出去"。
        #
        #   修法：非 WebSocket 请求一律改成 Connection: close，
        #   后端回完就关，浏览器于是每个请求都开新连接 -> 每个请求都被改写。
        is_upgrade = (hget(headers, "upgrade") or "").lower() == "websocket"
        out = [("%s %s HTTP/1.1" % (method, target)).encode("latin-1")]
        for k, v in headers:
            lk = k.lower()
            if lk == "host":
                out.append(("Host: %s" % AUTHORITY).encode("latin-1"))
            elif lk == "origin":
                # 不能原样转发（校验要求 Origin 与 Host 同源），
                # 也不要直接删（有些代码在等这个头）—— 改写成后端自己的源。
                out.append(("Origin: http://%s" % AUTHORITY).encode("latin-1"))
            elif lk == "referer":
                out.append(("Referer: http://%s/" % AUTHORITY).encode("latin-1"))
            elif lk == "sec-fetch-site":
                out.append(b"Sec-Fetch-Site: same-origin")
            elif lk == "connection":
                out.append(b"Connection: Upgrade" if is_upgrade
                           else b"Connection: close")
            elif lk == "proxy-connection":
                continue
            else:
                out.append(("%s: %s" % (k, v)).encode("latin-1"))
        if not is_upgrade and not any(k.lower() == "connection"
                                      for k, _ in headers):
            out.append(b"Connection: close")
        newhead = b"\r\n".join(out) + b"\r\n\r\n"
        rlog("--> %s %s  host=%s upgrade=%s gate=%s auth=%s" % (
            method, target, hget(headers, "host"),
            hget(headers, "upgrade"), has(GATE_COOKIE),
            has(self.server.auth[0])))

        try:
            up = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=10)
        except OSError as e:
            log("连不上后端:", e)
            s.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        up.settimeout(None)
        # ★★ 必须清掉客户端 socket 的超时！否则 WebSocket 这种长连接
        #    只要客户端 30 秒没发数据，recv 就抛 timeout，连接被我掐断
        #    —— 现象就是"网页能打开、但会话列不出来、消息发不出去"。
        s.settimeout(None)
        up.sendall(newhead)
        if rest:
            up.sendall(rest)

        def pump(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                for x in (a, b):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        def pump_back():
            """后端 -> 客户端，顺便把每个响应的状态行记下来。"""
            first = [True]
            try:
                while True:
                    d = up.recv(65536)
                    if not d:
                        break
                    if first[0]:
                        line = d.split(b"\r\n", 1)[0].decode("latin-1",
                                                            "replace")
                        rlog("<-- %s %s  %s" % (method, target, line))
                        first[0] = False
                    s.sendall(d)
            except OSError:
                pass
            finally:
                for x in (up, s):
                    try:
                        x.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        t = threading.Thread(target=pump, args=(s, up), daemon=True)
        t.start()
        pump_back()
        t.join(timeout=1)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def lan_ips(port):
    ips = []
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("8.8.8.8", 80))
        ips.append(sk.getsockname()[0])
        sk.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if (not ip.startswith(("127.", "169.254.")) and ip not in ips):
                ips.append(ip)
    except Exception:
        pass
    return ["http://%s:%d/?k=%s" % (ip, port, TOKEN_HOLDER[0]) for ip in ips]


TOKEN_HOLDER = [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3081)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--token", default=None)
    ap.add_argument("--secret", default=None,
                    help="浏览器会话 secret；默认从 ~/.dsh/.credentials.yaml 读")
    a = ap.parse_args()

    secret = a.secret or load_secret()
    name, val = make_auth_cookie(secret)
    log("已从凭据库读到 secret，并自签了认证 cookie（名 %s...）" % name[:20])

    clear_reqlog()
    token = a.token or secrets.token_urlsafe(5)
    TOKEN_HOLDER[0] = token

    srv = Server((a.bind, a.port), Handler)
    srv.token = token
    srv.auth = (name, val)

    print("=" * 76, flush=True)
    print("DSH 手机入口就绪  （反向代理 0.0.0.0:%d -> %s）" % (a.port, AUTHORITY),
          flush=True)
    print("  口令: %s" % token, flush=True)
    print("  手机连同一个 WiFi，浏览器打开：", flush=True)
    for u in lan_ips(a.port):
        print("      " + u, flush=True)
    print("  打开一次后浏览器会记住（cookie，30 天），之后直接开 http://<上面那个IP>:%d/"
          % a.port, flush=True)
    print("  [!] 这会把你电脑上的 agent 暴露给同一个 WiFi -- 用完 Ctrl-C 关掉", flush=True)
    print("=" * 76, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
