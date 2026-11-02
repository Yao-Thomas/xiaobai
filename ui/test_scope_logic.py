#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scope_logic.py —— 本地验证 scope.py 的仿真信号源 + 测量算法

不需要板子: Scope() 在没有 .scope_addr 标记时自动用内部仿真波形。
验证 measure() 算出来的 频率/峰峰值/占空比 和设定值一致。
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui"))

from scope import Scope, WAVE_SINE, WAVE_SQUARE, WAVE_TRI, WAVE_SAW, \
    WAVE_NAMES, TIMEBASES, freq_word, word_freq     # noqa: E402

FAIL = 0


def check(cond, msg):
    global FAIL
    if cond:
        print("    OK   %s" % msg)
    else:
        print("    FAIL %s" % msg)
        FAIL += 1


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


print("=" * 74)
print(" scope.py 逻辑自检 (仿真模式, 不需要板子)")
print("=" * 74)

sc = Scope(verbose=False)
print(" hw=%s why=%s" % (sc.hw, sc.why))
check(not sc.hw, "无标记时自动退化成仿真信号源")

# ---- 1. 频率字换算 ----
print("")
print("--- 频率字换算 ---")
for hz in (100.0, 1000.0, 10000.0, 100000.0):
    w = freq_word(hz)
    back = word_freq(w)
    err = abs(back - hz) / hz
    check(err < 1e-4, "%9.1f Hz -> 字 0x%08X -> %.3f Hz (误差 %.2e)"
          % (hz, w, back, err))

# ---- 2. 各波形 + 各时基下的测量 ----
print("")
print("--- 测量算法 (每种波形 x 几个频率) ---")
for tb in (0, 4, 7):
    div, dec, name = TIMEBASES[tb]
    ts = div * dec / 100e6
    sc.set_timebase(tb)
    print("  时基 %s  (每点 %.3g s, 窗口 %.4g s)"
          % (name, ts, 4096 * ts))
    for wv in (WAVE_SINE, WAVE_SQUARE, WAVE_TRI, WAVE_SAW):
        sc.sim_wave = wv
        # 选一个在窗口里正好 ~10 个周期的频率
        target = 10.0 / (4096 * ts)
        sc.sim_freq_hz = target
        data = sc.read_frame(4096)
        m = sc.measure(data)
        f = m.get("freq")
        rel = abs(f - target) / target if f else 9.9
        check(rel < 0.12,
              "%-4s 设 %9.1f Hz, 测 %9s Hz (偏差 %.1f%%), Vpp=%3d, 占空 %.1f%%"
              % (WAVE_NAMES[wv], target,
                 ("%.1f" % f) if f else "None", rel * 100,
                 m.get("pp", -1), m.get("duty", -1)))
        if wv == WAVE_SQUARE:
            check(near(m.get("duty"), 50.0, 6.0),
                  "  方波占空比应约 50%% (实测 %.1f%%)" % m.get("duty"))
        if wv in (WAVE_SINE, WAVE_TRI, WAVE_SAW):
            check(m.get("pp", 0) > 200,
                  "  %s 峰峰值应接近满量程 (实测 %d)" % (WAVE_NAMES[wv], m.get("pp")))
    print("")

# ---- 3. 频率单调性: 频率翻倍, 测量值也该翻倍 ----
print("--- 频率单调性 ---")
sc.set_timebase(4)
sc.sim_wave = WAVE_SINE
prev = 0.0
for k in (1, 2, 4, 8):
    f0 = 500.0 * k
    sc.sim_freq_hz = f0
    m = sc.measure(sc.read_frame(4096))
    f = m.get("freq") or 0.0
    check(f > prev and abs(f - f0) / f0 < 0.15,
          "设 %6.0f Hz -> 测 %8.1f Hz" % (f0, f))
    prev = f

# ---- 4. 边界: 全 0 / 全 255 不应崩 ----
print("")
print("--- 边界输入 ---")
for name, data in (("全 0", bytearray(4096)),
                   ("全 255", bytearray([255]) * 4096),
                   ("太短", bytearray(4))):
    try:
        m = sc.measure(data)
        check(True, "%s -> 没崩 (%s)" % (name, m.get("pp")))
    except Exception as ex:
        check(False, "%s -> 异常 %s" % (name, ex))

print("")
print("=" * 74)
if FAIL == 0:
    print(" ***** 全部通过 *****")
else:
    print(" ***** %d 项失败 *****" % FAIL)
print("=" * 74)
sys.exit(1 if FAIL else 0)
