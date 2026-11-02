import sys, urllib.request, urllib.error, http.cookiejar, socket, base64, os
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

def code(op, url, data=None, hdr=None, method=None):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (hdr or {}).items(): req.add_header(k, v)
    try:
        r = op.open(req, timeout=8)
        return r.status, r.read(200)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200)
    except Exception as e:
        return "ERR", str(e).encode()

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

print("=== A. 拿 cookie ===")
print("  带口令:", code(op, "http://127.0.0.1:3081/?k=xb7k2m9q")[0])
print("  cookies:", [c.name[:24] for c in cj])

print()
print("=== B. /api 各种方法（这是手机发消息要走的通道）===")
for m, d in (("GET", None), ("POST", b"{}"), ("POST", b'{"jsonrpc":"2.0","id":1,"method":"ping"}')):
    print("  %-5s /api  -> %s  %s" % (m, code(op, "http://127.0.0.1:3081/api", d,
          {"Content-Type": "application/json"}, m)[0],
          code(op, "http://127.0.0.1:3081/api", d, {"Content-Type": "application/json"}, m)[1][:80]))

print()
print("=== C. 不带 cookie 打 /api（对照）===")
op2 = urllib.request.build_opener()
print("  ->", code(op2, "http://127.0.0.1:3081/api", b"{}", {"Content-Type": "application/json"}, "POST")[0],
      "（如果也是通的说明我的门禁有漏洞）")

print()
print("=== D. WebSocket 握手能不能过代理 ===")
key = base64.b64encode(os.urandom(16)).decode()
for path in ("/api", "/api/stream", "/api/ws"):
    try:
        s = socket.create_connection(("127.0.0.1", 3081), timeout=6)
        ck = "; ".join("%s=%s" % (c.name, c.value) for c in cj)
        s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:3081\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
                   "Cookie: %s\r\nOrigin: http://127.0.0.1:3081\r\n\r\n"
                   % (path, key, ck)).encode())
        s.settimeout(5)
        resp = s.recv(300).decode("latin-1", "replace")
        print("  %-12s -> %s" % (path, resp.split("\r\n")[0]))
        s.close()
    except Exception as e:
        print("  %-12s -> 异常 %s" % (path, e))