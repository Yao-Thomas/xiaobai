#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_notify.py —— 把"网址自动推微信"接进 tunnel.py

效果：隧道每次启动拿到新网址后，自动调用 notify_url.push()，
      把新网址发到微信，人在外面也能看到。
"""
import io
import sys

P = "tunnel.py"
src = io.open(P, encoding="utf-8").read()

if "notify_url" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# 1) 拿到网址后，顺手推微信
old = '''    if url:
        with open(URLFILE, "w", encoding="utf-8") as f:
            f.write(url)
        print()
'''
new = '''    if url:
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
                    "电脑上的公网隧道已启动。\\n\\n"
                    "**手机点这个就能进（流量也可以）：**\\n\\n"
                    "%s/?k=xb7k2m9q\\n\\n"
                    "局域网（手机开着热点时更快）：\\n"
                    "http://192.168.10.17:3081/?k=xb7k2m9q\\n" % url)
                print("[微信推送] %s" % msg, flush=True)
            else:
                print("[微信推送] 没配 key，跳过（python notify_url.py --key SCTxxx）",
                      flush=True)
        except Exception as e:
            print("[微信推送] 失败: %s" % e, flush=True)
        print()
'''
assert old in src, "锚点没找到"
src = src.replace(old, new, 1)

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
