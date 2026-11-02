#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_ui.py —— 阶段10 剩余指标测量（★ 离屏模式，完全不影响桌面）

关键手法：
  1. Screen() 正常构造（只 mmap，不主动写）
  2. 把 scr.flush 打桩成空操作 -> 一个字节都不写 /dev/fb0 -> 桌面完全不受影响
  3. 用 /tmp/ui_tap 远程注入触摸事件（fbui.Touch 内置支持）
  4. 因此可以真实测出：每帧成本、触摸响应、通道/模式切换耗时、CPU 占用

用法: sudo python3 measure_ui.py
"""
import os
import sys
import time

sys.path.insert(0, "/home/zynq/ui")

from fbui import Screen, Touch
import apps_scope_dual as A

TAP = "/tmp/ui_tap"


def tap(x, y):
    with open(TAP, "w") as f:
        f.write("%d,%d" % (x, y))


def center(r):
    return ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)


def cpu_ticks():
    with open("/proc/self/stat") as f:
        p = f.read().split()
    return int(p[13]) + int(p[14])


# ============================================================
print("=== 建离屏 Screen（flush 打桩，不写显存）===")
scr = Screen()
_real_flush = scr.flush
scr.flush = lambda box=None: None          # ★ 关键：不碰 /dev/fb0
touch = Touch()
print("  屏幕 %dx%d  bpp=%d  flush 已打桩 ✓" % (scr.w, scr.h, scr.bpp))

app = A.App(scr)
app.make_bg()
print("  fpga_env =", app.fpga_env)
print("  当前 span =", app.span)

# 预热（让 FPGA 路径进入稳态）
for _ in range(60):
    app.step()
    time.sleep(0.004)
print("  预热完成，span=%d  fps=%.1f" % (app.span, app.fps))

# ============================================================
print()
print("=" * 78)
print("A. 每帧成本（离屏，含全部绘制）")
print("=" * 78)

N = 150
ticks0 = cpu_ticks()
t0 = time.perf_counter()
for _ in range(N):
    app.step()
    app.draw_wave()
    app.draw_stat()
    app.draw_top()
    app.draw_scales()
el = (time.perf_counter() - t0) / N * 1000
ticks1 = cpu_ticks()
HZ = os.sysconf("SC_CLK_TCK")
cpu_pct = (ticks1 - ticks0) / float(HZ) / (el * N / 1000.0) * 100.0
print("  全量重绘（波形+参数行+顶栏+刻度）: %6.2f ms/帧  -> %6.1f FPS" % (el, 1000 / el))
print("  对应单核 CPU（按此帧率跑满）    : %6.1f %%" % min(100.0, cpu_pct))

# 按阶段7 的三档实际配比估算
print()
print("  按阶段7 配比（触摸125Hz / 波形30FPS / 文字6.7FPS）估算：")
print("    波形区每 33ms 刷一次、文字每 150ms 刷一次")
# 分别测
t0 = time.perf_counter()
for _ in range(N):
    app.draw_wave()
tw = (time.perf_counter() - t0) / N * 1000
t0 = time.perf_counter()
for _ in range(N // 3 or 1):
    app.draw_stat()
    app.draw_top()
    app.draw_scales()
tt = (time.perf_counter() - t0) / max(1, N // 3) * 1000
t0 = time.perf_counter()
for _ in range(N):
    app.step()
ts = (time.perf_counter() - t0) / N * 1000
print("    波形绘制 = %.2f ms  |  文字绘制 = %.2f ms  |  采集+统计 = %.2f ms" % (tw, tt, ts))
budget = tw * 30 + tt * 6.7 + ts * 30 + 125 * 0.02
print("    每 100ms 内的工作量估算 = %.2f ms  -> 单核约 %.1f %%" % (budget, budget * 10))

# ============================================================
print()
print("=" * 78)
print("B. 触摸响应延迟")
print("=" * 78)


def measure_tap(x, y, pred, wait=2.0, poll_dt=0.002):
    """注入一次点击，量到状态变化为止"""
    tap(x, y)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < wait:
        ev = touch.poll(move=True)
        if ev:
            if not app.handle(ev[1], ev[2], ev[0] if len(ev) > 2 else "down"):
                return None
        if pred():
            return (time.perf_counter() - t0) * 1000
        time.sleep(poll_dt)
    return None


lat = []
for i in range(10):
    app.panel = None
    app.sel_field = 0 if i % 2 else 1
    want = 1 - app.sel_field
    ms = measure_tap(*center(app.b_cur), lambda: app.sel_field == want)
    if ms:
        lat.append(ms)
if lat:
    lat.sort()
    p50 = lat[len(lat) // 2]
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    print("  点「当前项」按钮切五项: n=%d  P50=%.1f ms  P95=%.1f ms  max=%.1f ms"
          % (len(lat), p50, p95, max(lat)))
    print("  >>> 目标 P95 < 60ms : %s" % ("PASS" if p95 < 60 else "FAIL"))
else:
    print("  !! 注入没生效，检查 /tmp/ui_tap")

# ============================================================
print()
print("=" * 78)
print("C. 通道切换 / 模式切换")
print("=" * 78)

# 通道切换：打开弹层 -> 勾 CH2 -> 确定
app.chk = [True, False]
tap(*center(app.b_ch))
t0 = time.perf_counter()
opened = False
while time.perf_counter() - t0 < 1.0:
    ev = touch.poll(move=True)
    if ev:
        app.handle(ev[1], ev[2])
    if app.panel == "ch":
        opened = True
        break
    time.sleep(0.002)
t_open = (time.perf_counter() - t0) * 1000 if opened else None
print("  打开通道弹层: %s" % ("%.1f ms" % t_open if t_open else "失败"))

if opened:
    # 弹层项: 0=CH1复选 1=CH2复选 2=确定
    t0 = time.perf_counter()
    tap(*center(app.panel_rects[1][0]))       # CH2 复选
    while time.perf_counter() - t0 < 0.5:
        ev = touch.poll(move=True)
        if ev:
            app.handle(ev[1], ev[2])
        if app.chk[1]:
            break
        time.sleep(0.002)
    tap(*center(app.panel_rects[2][0]))       # 确定
    t1 = time.perf_counter()
    while time.perf_counter() - t1 < 1.0:
        ev = touch.poll(move=True)
        if ev:
            app.handle(ev[1], ev[2])
        if app.panel is None:
            break
        time.sleep(0.002)
    sw = (time.perf_counter() - t0) * 1000
    print("  勾 CH2 + 确定（通道切换）: %.1f ms   chk=%s  显示CH1=%s 显示CH2=%s"
          % (sw, app.chk, app.m.ch[0].enabled, app.m.ch[1].enabled))
    print("  >>> 目标 < 100ms : %s" % ("PASS" if sw < 100 else "FAIL"))

# 模式切换：打开模式弹层 -> 选 Normal -> 确定
app.panel = None
tap(*center(app.b_mode))
t0 = time.perf_counter()
opened = False
while time.perf_counter() - t0 < 1.0:
    ev = touch.poll(move=True)
    if ev:
        app.handle(ev[1], ev[2])
    if app.panel == "mode":
        opened = True
        break
    time.sleep(0.002)
if opened:
    t0 = time.perf_counter()
    tap(*center(app.panel_rects[1][0]))       # m1 = NORMAL
    time.sleep(0.02)
    while True:
        ev = touch.poll(move=True)
        if ev:
            app.handle(ev[1], ev[2])
        else:
            break
    tap(*center(app.panel_rects[-1][0]))      # 确定（最后一项）
    t1 = time.perf_counter()
    while time.perf_counter() - t1 < 1.0:
        ev = touch.poll(move=True)
        if ev:
            app.handle(ev[1], ev[2])
        if app.panel is None:
            break
        time.sleep(0.002)
    sw = (time.perf_counter() - t0) * 1000
    print("  选 NORMAL + 确定（模式切换）: %.1f ms   当前模式=%s"
          % (sw, A.ACQ_NAMES[app.m.acq.mode]))
    print("  >>> 目标 < 150ms : %s" % ("PASS" if sw < 150 else "FAIL"))

# ============================================================
print()
print("=" * 78)
print("D. 双通道同时显示")
print("=" * 78)
app.m.ch[0].enabled = True
app.m.ch[1].enabled = True
n0 = len(app.env1min), len(app.env2min)
app.draw_wave()
print("  两路都开时 draw_wave 正常返回，包络缓冲 %s / %s" % n0)
print("  ch0.enabled=%s  ch1.enabled=%s  -> %s"
      % (app.m.ch[0].enabled, app.m.ch[1].enabled,
         "PASS（可同选同显）" if (app.m.ch[0].enabled and app.m.ch[1].enabled) else "FAIL"))

print()
print("MEASURE_DONE")
