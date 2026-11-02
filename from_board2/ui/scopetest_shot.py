#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scopetest_shot.py —— 独立跑一遍示波器应用 (不走触摸), 停在画面上等截图

桌面要先停掉。用来验证 apps_scope.py + libscope.so + PL 采集器 整条链路。
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui                                     # noqa: E402
import apps_scope as A                          # noqa: E402

scr = fbui.Screen()
if getattr(scr, "yoff", 0) != 0:
    try:
        scr.pan(0)
    except Exception as e:
        print("pan(0) failed:", e)

app = A.ScopeApp(scr)
print("hw =", app.sc.hw, " why =", app.sc.why)
print("base = 0x%08X" % app.sc.base)
if app.sc.hw:
    print("status =", app.sc.status())

app.make_bg()
scr.flush()
app.draw_stat()
app.draw_wave()

# 跑几帧, 每帧换个波形, 最后停在正弦
for w in (A.WAVE_SINE, A.WAVE_SQUARE, A.WAVE_TRI, A.WAVE_SAW, A.WAVE_SINE):
    app.wave = w
    app.sc.configure(wave=w)
    for _ in range(3):
        app.step()
        app.draw_wave()
        app.draw_stat()
    m = app.meas
    print("wave=%s freq=%s pp=%s min=%s max=%s duty=%.1f%% edges=%s"
          % (A.WAVE_NAMES[w],
             ("%.2f Hz" % m["freq"]) if m.get("freq") else None,
             m.get("pp"), m.get("min"), m.get("max"),
             m.get("duty", 0.0), m.get("edges")))

# 再演示两个时基档
for tb in (2, 4, 7, 4):
    app.tb = tb
    app.apply()
    for _ in range(2):
        app.step()
        app.draw_wave()
        app.draw_stat()
    m = app.meas
    print("timebase=%s freq=%s pp=%s edges=%s"
          % (A.TIMEBASES[tb][2],
             ("%.2f Hz" % m["freq"]) if m.get("freq") else None,
             m.get("pp"), m.get("edges")))

# 触发模式
for mode in (A.MODE_NORMAL, A.MODE_SINGLE, A.MODE_AUTO):
    app.mode = mode
    app.sc.configure(mode=mode)
    app.step()
    app.draw_wave()
    app.draw_stat()
    print("mode=%s status=%s" % (A.MODE_NAMES[mode], app.sc.status()))

print("SCREEN_READY")
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
