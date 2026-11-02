#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scopetiming_shot.py —— 量一下示波器每帧时间花在哪 (需要桌面停掉)

插桩: 采集 / 读缓冲 / 测量 / 画波形 / flush 分段计时
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
    except Exception:
        pass

app = A.ScopeApp(scr)
print("hw =", app.sc.hw)
app.make_bg()
scr.flush()

N = 20
s_cap = s_read = s_meas = s_draw = s_flush = 0.0
for i in range(N):
    t0 = time.time()
    ok = app.sc.capture()
    t1 = time.time()
    data = app.sc.read_frame(4096)
    t2 = time.time()
    m = app.sc.measure(data)
    t3 = time.time()
    app.data = data
    app.meas = m
    app.draw_wave()
    t4 = time.time()
    app.draw_stat()
    t5 = time.time()
    s_cap += (t1 - t0) * 1000
    s_read += (t2 - t1) * 1000
    s_meas += (t3 - t2) * 1000
    s_draw += (t4 - t3) * 1000
    s_flush += (t5 - t4) * 1000

print("每帧分段 (平均 %d 帧):" % N)
print("  采集(含等触发) %7.2f ms" % (s_cap / N))
print("  读 4096 样本   %7.2f ms" % (s_read / N))
print("  测量           %7.2f ms" % (s_meas / N))
print("  画波形         %7.2f ms" % (s_draw / N))
print("  状态栏+flush   %7.2f ms" % (s_flush / N))
tot = (s_cap + s_read + s_meas + s_draw + s_flush) / N
print("  合计           %7.2f ms  -> %.1f FPS" % (tot, 1000.0 / max(tot, 1e-6)))

# 再单独量 flush 的成本
t0 = time.time()
for _ in range(10):
    app.draw_wave()
print("draw_wave 单独      %7.2f ms" % ((time.time() - t0) * 100))

t0 = time.time()
for _ in range(10):
    scr.flush(box=(A.WAVE[0], A.WAVE[1], A.WAVE[2] + 1, A.WAVE[3] + 1))
print("wave area flush     %7.2f ms" % ((time.time() - t0) * 100))

t0 = time.time()
for _ in range(10):
    app.sc.read_frame(4096)
print("read_frame 单独     %7.2f ms" % ((time.time() - t0) * 100))

app.draw_wave()
app.draw_stat()
print("SCREEN_READY")
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
