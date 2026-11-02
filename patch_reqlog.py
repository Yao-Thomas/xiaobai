#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_reqlog.py —— 给 dsh_proxy.py 加请求日志（诊断手机端卡在哪一步）"""
import io
import sys

P = "dsh_proxy.py"
src = io.open(P, encoding="utf-8").read()

if "def rlog(" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

old1 = '''def log(*a):
    print("[proxy]", *a, flush=True)
'''
new1 = '''REQLOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "dsh_proxy_req.log")


def log(*a):
    print("[proxy]", *a, flush=True)


def rlog(s):
    """把每个请求/响应写进日志文件，方便诊断手机端到底卡在哪一步。"""
    try:
        with open(REQLOG, "a", encoding="utf-8") as f:
            f.write("%s %s\\n" % (time.strftime("%H:%M:%S"), s))
    except Exception:
        pass


def clear_reqlog():
    try:
        open(REQLOG, "w").close()
    except Exception:
        pass
'''
assert old1 in src, "锚点1没找到"
src = src.replace(old1, new1, 1)

old2 = '        newhead = b"\\r\\n".join(out) + b"\\r\\n\\r\\n"\n'
new2 = ('        newhead = b"\\r\\n".join(out) + b"\\r\\n\\r\\n"\n'
        '        rlog("--> %s %s  host=%s upgrade=%s gate=%s auth=%s" % (\n'
        '            method, target, hget(headers, "host"),\n'
        '            hget(headers, "upgrade"), has(GATE_COOKIE),\n'
        '            has(self.server.auth[0])))\n')
assert old2 in src, "锚点2没找到"
src = src.replace(old2, new2, 1)

old3 = '''        t = threading.Thread(target=pump, args=(s, up), daemon=True)
        t.start()
        pump(up, s)
        t.join(timeout=1)
'''
new3 = '''        def pump_back():
            """后端 -> 客户端，顺便把每个响应的状态行记下来。"""
            first = [True]
            try:
                while True:
                    d = up.recv(65536)
                    if not d:
                        break
                    if first[0]:
                        line = d.split(b"\\r\\n", 1)[0].decode("latin-1",
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
'''
assert old3 in src, "锚点3没找到"
src = src.replace(old3, new3, 1)

# 启动时清空日志
src = src.replace('    token = a.token or secrets.token_urlsafe(5)',
                  '    clear_reqlog()\n    token = a.token or secrets.token_urlsafe(5)', 1)

io.open(P, "w", encoding="utf-8").write(src)
print("补丁完成")
