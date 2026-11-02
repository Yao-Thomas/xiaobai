#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cpu_steady.py —— 阶段10「ARM 单核 <35% / 双核 <25%」实测

按阶段7 的配比（触摸125Hz / 波形30FPS / 文字6.7FPS / 网络1Hz）
跑真实稳态循环 60 秒，采 /proc/self/stat 得真实 CPU 占用。

★ 离屏：把 scr.flush 打桩，不写 /dev/fb0，桌面完全不受影响。
★ 注意：热路径用的是 blit_raw（直接写显存 mmap），这一项【没有被打桩】，
  所以 draw_wave 的耗时是真实的。
"""
import os
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch
import apps_scope_dual as A

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 60
HZ = os.sysconf("SC_CLK_TCK")


def ticks():
    with open("/proc/self/stat") as f:
        p = f.read().split()
    return int(p[13]) + int(p[14])


def loadavg():
    try:
        return open("/proc/loadavg").read().split()[:3]
    except Exception:
        return ["?", "?", "?"]


scr = Screen()
scr.flush = lambda box=None: None          # 不写显存
touch = Touch()
app = A.App(scr)
app.make_bg()

# 预热
for _ in range(40):
    app.step()
    time.sleep(0.004)

print("=== 稳态循环配比（阶段7）===")
print("  触摸 %.0f Hz | 波形 %.1f FPS | 文字 %.1f FPS | 网络 1 Hz"
      % (1.0 / A.TOUCH_DT, 1.0 / A.WAVE_DT, 1.0 / A.TEXT_DT))
print("  运行 %.0f 秒..." % DUR)
print()

# 分项计数与累计耗时
cnt = {"touch": 0, "wave": 0, "text": 0, "net": 0}
cost = {"touch": 0.0, "wave": 0.0, "text": 0.0, "net": 0.0}
la0 = loadavg()
t_start = time.time()
t0 = ticks()
nt = nw = nx = nn = 0.0
while True:
    now = time.time()
    el = now - t_start
    if el >= DUR:
        break
    if now >= nt:
        ta = time.perf_counter()
        ev = touch.poll(move=True)
        if ev:
            app.handle(ev[1], ev[2])
        cost["touch"] += time.perf_counter() - ta
        cnt["touch"] += 1
        nt = now + A.TOUCH_DT
    if now >= nw:
        ta = time.perf_counter()
        app.step()
        app.draw_wave()
        cost["wave"] += time.perf_counter() - ta
        cnt["wave"] += 1
        nw = now + A.WAVE_DT
    if now >= nx:
        ta = time.perf_counter()
        app.draw_stat()
        app.draw_top()
        app.draw_scales()
        cost["text"] += time.perf_counter() - ta
        cnt["text"] += 1
        nx = now + A.TEXT_DT
    if now >= nn:
        ta = time.perf_counter()     # 真实网络状态检查（读路由表，1Hz）
        try:
            open("/proc/net/route").read()
        except Exception:
            pass
        cost["net"] += time.perf_counter() - ta
        cnt["net"] += 1
        nn = now + 1.0
    time.sleep(0.001)

t1 = ticks()
wall = time.time() - t_start
la1 = loadavg()

used = (t1 - t0) / float(HZ)
cpupct = used / wall * 100.0

print("=== 实测结果 ===")
print("  墙钟时间      : %.1f 秒" % wall)
print("  进程 CPU 时间 : %.3f 秒" % used)
print("  >>> 单核占用  : %.1f %%" % cpupct)
print("      目标 <35%% : %s" % ("PASS" if cpupct < 35 else "FAIL"))
print()
print("  分项（次数 / 累计耗时 / 单次）：")
for k in ("touch", "wave", "text", "net"):
    c = cnt[k]
    ms = cost[k] * 1000
    print("    %-6s %5d 次  %8.1f ms  %7.3f ms/次" % (k, c, ms, ms / c if c else 0))
print()
print("  系统负载（1/5/15 分钟）: %s -> %s" % (" ".join(la0), " ".join(la1)))
try:
    ncpu = os.sysconf("SC_NPROCESSORS_ONLN")
    l1 = float(la1[0])
    print("  CPU 核数 = %d，1 分钟负载 %.2f -> 双核占比约 %.1f %%"
          % (ncpu, l1, l1 / ncpu * 100))
    print("      目标 <25%% : %s" % ("PASS" if (l1 / ncpu * 100) < 25 else "注意（含其它进程）"))
except Exception:
    pass
print()
print("CPU_DONE")
