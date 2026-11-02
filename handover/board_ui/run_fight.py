#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_fight.py —— 独立跑 apps_fight (调试用, 不经过桌面)

用法:  sudo python3 run_fight.py [秒数]
"""
import sys
import time
import traceback

sys.path.insert(0, "/home/zynq/ui")
import fbui
import apps_fight

limit = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
scr = fbui.Screen()
touch = fbui.Touch()
print("FIGHT START", flush=True)
t0 = time.time()
try:
    if limit > 0:
        import threading

        def killer():
            time.sleep(limit)
            print("FIGHT TIMEOUT -> exit", flush=True)
            import os
            os._exit(0)
        threading.Thread(target=killer, daemon=True).start()
    apps_fight.run(scr, touch)
    print("FIGHT RETURNED ok  %.1fs" % (time.time() - t0), flush=True)
except Exception:
    traceback.print_exc()
    print("FIGHT CRASHED  %.1fs" % (time.time() - t0), flush=True)
