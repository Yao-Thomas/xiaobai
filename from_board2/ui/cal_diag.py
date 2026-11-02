#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal_diag.py —— 电压测量诊断：重复性 + 两点标定

用法（板上 sudo）：
    sudo python3 cal_diag.py rep CH1          # 重复性检查：同一信号连读 10 次
    sudo python3 cal_diag.py dc  CH1 0.0 4.0  # 直流两点标定（零点+增益都能定）
    sudo python3 cal_diag.py pp  CH1 1.0 4.0  # Vpp 两点标定（只能定增益）

为什么分 dc / pp：
    vpp = (max-zero)*K*gain - (min-zero)*K*gain = (max-min)*K*gain
    -> zero 被消掉 -> 用 Vpp 永远标不出零点，只能用直流标。
"""
import ctypes
import json
import os
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import scope_dual as sd
from scope_processing import V_FULL, SAMPLE_MAX, CAL_ZERO, CAL_GAIN

N = 4096
K = V_FULL / SAMPLE_MAX
CAL_FILE = "/home/zynq/ui/scope_cal.json"


def read_once(d, ch):
    b1 = (ctypes.c_ushort * N)()
    b2 = (ctypes.c_ushort * N)()
    ifo = (ctypes.c_uint * 8)()
    mo = (ctypes.c_int * 7)()
    if d.lib.sd_read_frame_locked(b1, b2, ctypes.c_int(N), ifo) <= 0:
        return None
    buf = b1 if ch == 0 else b2
    d.lib.sd_measure(buf, ctypes.c_int(N), mo)
    return mo[0], mo[1]


def sample_avg(d, ch, n=6):
    """读 n 次取中位，返回 (mid_lsb, pp_lsb)"""
    ms, ps = [], []
    for _ in range(n):
        r = read_once(d, ch)
        if r:
            ms.append((r[0] + r[1]) / 2.0)
            ps.append(r[1] - r[0])
        time.sleep(0.15)
    if not ms:
        return None
    ms.sort()
    ps.sort()
    return ms[len(ms) // 2], ps[len(ps) // 2]


def save_cal(ch, zero, gain):
    data = {}
    try:
        if os.path.exists(CAL_FILE):
            data = json.load(open(CAL_FILE))
    except Exception:
        data = {}
    data["ch%d" % ch] = {"zero": round(zero, 4), "gain": round(gain, 6)}
    try:
        with open(CAL_FILE, "w") as f:
            json.dump(data, f, indent=2)
        os.system("sync")
        print("")
        print("已写入 %s:" % CAL_FILE)
        print(json.dumps(data, indent=2))
        print("重启桌面（或退出重进示波器）后生效")
    except Exception as e:
        print("写文件失败:", e)
        print('请手工建 %s: {"ch%d": {"zero": %.4f, "gain": %.6f}}'
              % (CAL_FILE, ch, zero, gain))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    mode = sys.argv[1]
    ch = 0 if sys.argv[2].upper() in ("CH1", "0") else 1

    d = sd.ScopeDual(verbose=False)
    if not d.hw:
        print("hw 打不开:", d.why)
        return 1
    d.set_acqmode(0)
    d.configure(triglev=512, pre=2048)
    time.sleep(0.5)

    print("通道 CH%d   名义 K=%.8f V/LSB   内置默认 zero=%.1f gain=%.3f"
          % (ch + 1, K, CAL_ZERO, CAL_GAIN))
    try:
        print("当前标定文件:", json.load(open(CAL_FILE)))
    except Exception:
        print("当前标定文件: (不存在，用名义值)")
    print("")

    if mode == "rep":
        pps, mids = [], []
        for i in range(10):
            r = read_once(d, ch)
            if r is None:
                print("  读帧失败")
                continue
            mn, mx = r
            pp = mx - mn
            mid = (mn + mx) / 2.0
            pps.append(pp)
            mids.append(mid)
            print("  #%2d  min=%4d max=%4d  pp=%4d (%.4fV)  mid=%.1f (%.4fV)"
                  % (i + 1, mn, mx, pp, pp * K, mid, (mid - 511.5) * K))
            time.sleep(0.25)
        if not pps:
            print("没有读到数据")
            return 1
        p0 = sorted(pps)
        med = p0[len(p0) // 2]
        spread = (p0[-1] - p0[0]) * 100.0 / max(1, med)
        m0 = sorted(mids)
        print("")
        print("=== 重复性 ===")
        print("  pp  : min=%d max=%d 中位=%d (%.4fV)  散差=%.2f%%"
              % (p0[0], p0[-1], med, med * K, spread))
        print("  mid : min=%.1f max=%.1f  散差=%.1f LSB"
              % (m0[0], m0[-1], m0[-1] - m0[0]))
        print("")
        if spread > 5:
            print("  >>> 散差 >5%：测量本身不可重复，先别标定！")
            print("      可能原因：信号源不稳 / 触发电平压在跳变沿 / 一屏周期数太少")
        else:
            print("  >>> 散差可接受，可以做标定")
        print("DIAG_REP_DONE")
        return 0

    if len(sys.argv) < 5:
        print("需要两个已知值，例如: %s %s CH1 1.0 4.0" % (sys.argv[0], mode))
        return 1
    v1 = float(sys.argv[3])
    v2 = float(sys.argv[4])

    print("把信号源设成 %.4f，稳定后按回车..." % v1)
    try:
        input()
    except Exception:
        pass
    r1 = sample_avg(d, ch)
    if r1 is None:
        print("读不到数据")
        return 1
    print("  读得 mid=%.2f pp=%d" % r1)

    print("把信号源设成 %.4f，稳定后按回车..." % v2)
    try:
        input()
    except Exception:
        pass
    r2 = sample_avg(d, ch)
    if r2 is None:
        print("读不到数据")
        return 1
    print("  读得 mid=%.2f pp=%d" % r2)
    print("")

    if mode == "dc":
        L1 = r1[0]
        L2 = r2[0]
        if abs(L2 - L1) < 3:
            print("!! 两点的 ADC 码太接近，信号没变？")
            return 1
        B = (v2 - v1) / (L2 - L1)
        zero = L1 - v1 / B
        gain = B / K
        print("=== DC 模式（零点+增益都能定）===")
        print("  B    = %.8f V/LSB" % B)
        print("  zero = %.3f" % zero)
        print("  gain = %.6f" % gain)
        for V, L in ((v1, L1), (v2, L2)):
            print("    真实%.4fV -> 新参数算得 %.4fV" % (V, (L - zero) * K * gain))
    else:
        L1 = r1[1]
        L2 = r2[1]
        g1 = v1 / (L1 * K) if L1 else 0.0
        g2 = v2 / (L2 * K) if L2 else 0.0
        print("=== Vpp 模式（只能定增益）===")
        print("  由点1 得 gain = %.6f" % g1)
        print("  由点2 得 gain = %.6f" % g2)
        if g1 and g2 and abs(g1 - g2) / max(g1, g2) > 0.05:
            print("  >>> 两点算出的 gain 差 %.1f%% -> 非线性或测量不稳"
                  % (abs(g1 - g2) / max(g1, g2) * 100))
        gain = (g1 + g2) / 2.0 if (g1 and g2) else (g1 or g2 or 1.0)
        zero = CAL_ZERO
        print("  取平均: zero=%.3f(名义) gain=%.6f" % (zero, gain))

    save_cal(ch, zero, gain)
    print("DIAG_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
