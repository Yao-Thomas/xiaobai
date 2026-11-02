import socket, sys, time, base64, os
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
# 发一个 WS 升级请求到 /api（路径不对后端会回 404，但重点是我这边会不会 30 秒断）
key = base64.b64encode(os.urandom(16)).decode()
s = socket.create_connection(("127.0.0.1", 3081), timeout=6)
s.sendall(("GET /api HTTP/1.1\r\nHost: 127.0.0.1:3081\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % key).encode())
s.settimeout(5)
try:
    first = s.recv(200).decode("latin-1","replace").split("\r\n")[0]
except Exception as e:
    first = "无响应(%s)" % e
print("  首行响应:", first)
# 之后静默 40 秒（超过旧的 30 秒超时），看连接还在不在
print("  静默 35 秒 ...")
t0 = time.time()
try:
    s.settimeout(40)
    d = s.recv(100)
    print("  35 秒后收到 %d 字节 -> 连接%s" % (len(d), "被关闭（后端关的）" if not d else "还活着"))
except socket.timeout:
    print("  [X] 35 秒后仍无数据但连接没断（客户端超时）")
except Exception as e:
    print("  异常:", e)
print("  用时 %.1f 秒" % (time.time()-t0))
s.close()