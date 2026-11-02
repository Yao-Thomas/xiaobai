#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tap_probe.py —— 单独验证触摸注入通不通 (不启动 MC)

用法(板子上):  sudo python3 tap_probe.py [秒数]
"""
import os
import sys
import time
import traceback

sys.path.insert(0, "/home/zynq/ui")
import fbui

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
t = fbui.Touch()
print("touch=%s down=%s x=%d y=%d" % (t.path, t.down, t.x, t.y), flush=True)

# ---- 直接测 _load_inject, 把异常打出来 ----
print("--- 直接测 _load_inject ---", flush=True)
for i in range(3):
    if os.path.exists("/tmp/ui_tap"):
        raw = open("/tmp/ui_tap", "rb").read()
        print("  文件存在, 内容=%r" % raw, flush=True)
    else:
        print("  文件不存在", flush=True)
        time.sleep(0.5)
        continue
    try:
        r = t._load_inject()
        print("  _load_inject() -> %r" % (r,), flush=True)
    except Exception:
        traceback.print_exc()
    time.sleep(0.3)

print("--- 循环 poll %g 秒 ---" % secs, flush=True)
t0 = time.time()
n = 0
while time.time() - t0 < secs:
    ev = t.poll(move=True)
    if ev is not None:
        n += 1
        print("EV %-6s x=%-5d y=%-5d  (down=%s)" % (ev[0], ev[1], ev[2], t.down),
              flush=True)
    time.sleep(0.02)
print("共收到 %d 个事件" % n, flush=True)
