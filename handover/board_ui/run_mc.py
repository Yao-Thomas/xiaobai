#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_mc.py —— 独立跑 apps_mc (调试用, 不经过桌面)

用法:  sudo python3 run_mc.py [秒数] [--events]
       秒数    0/省略 = 一直跑
       --events 把每个触摸事件打到 stdout (排查"点了没反应")
"""
import sys
import time
import traceback

sys.path.insert(0, "/home/zynq/ui")
import fbui
import apps_mc

args = [a for a in sys.argv[1:] if not a.startswith("--")]
limit = float(args[0]) if args else 0.0
want_events = "--events" in sys.argv

scr = fbui.Screen()
touch = fbui.Touch()

if want_events:
    _orig = touch.poll

    def _poll(*a, **k):
        ev = _orig(*a, **k)
        if ev is not None:
            print("EV %r  down=%s" % (ev, touch.down), flush=True)
        return ev

    touch.poll = _poll
    print("events logging on", flush=True)

print("MC START", flush=True)
t0 = time.time()
try:
    if limit > 0:
        import threading

        def killer():
            time.sleep(limit)
            print("MC TIMEOUT -> exit", flush=True)
            import os
            os._exit(0)
        threading.Thread(target=killer, daemon=True).start()
    apps_mc.run(scr, touch)
    print("MC RETURNED ok  %.1fs" % (time.time() - t0), flush=True)
except Exception:
    traceback.print_exc()
    print("MC CRASHED  %.1fs" % (time.time() - t0), flush=True)
