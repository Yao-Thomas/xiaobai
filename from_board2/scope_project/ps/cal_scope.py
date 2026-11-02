#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal_scope.py —— 两点电压自标定工具

原理（两点定一条直线，同时解出零点偏移和斜率）：
    V = (lsb - zero) * (V_FULL / SAMPLE_MAX) * gain
令 K = V_FULL/SAMPLE_MAX，则    V = (lsb - zero) * K * gain
两点 (lsb1, V1) (lsb2, V2) 解得：
    B    = (V2 - V1) / (lsb2 - lsb1)     真正的 V/LSB
    zero = lsb1 - V1 / B
    gain = B / K

★ 关键：本工具读的是【原始 ADC 码】（C 的 sd_measure 返回的 1%/99% 分位，
  它不知道任何标定系数），所以反复标定都不会叠加误差。

用法（板上 sudo 跑）：
    sudo python3 cal_scope.py            # 交互：依次给两个已知电压
    sudo python3 cal_scope.py 1.0 4.0    # 直接指定两个已知电压值
"""
import ctypes
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import scope_dual as sd
from scope_processing import V_FULL, SAMPLE_MAX

N = 4096
K = V_FULL / SAMPLE_MAX


def read_lsb(d, ch, secs=0.8):
    """读若干帧，返回该通道的稳健 (min_lsb, max_lsb) 中值，以及中点"""
    b1 = (ctypes.c_ushort * N)()
    b2 = (ctypes.c_ushort * N)()
    ifo = (ctypes.c_uint * 8)()
    mo = (ctypes.c_int * 7)()
    mins, maxs = [], []
    t0 = time.time()
    while time.time() - t0 < secs:
        if d.lib.sd_read_frame_locked(b1, b2, ctypes.c_int(N), ifo) > 0:
            buf = b1 if ch == 0 else b2
            d.lib.sd_measure(buf, ctypes.c_int(N), mo)
            if (mo[1] - mo[0]) >= 0:
                mins.append(mo[0])
                maxs.append(mo[1])
        time.sleep(0.02)
    if not mins:
        return None, None
    mins.sort()
    maxs.sort()
    # 取中位数，抗离群
    return mins[len(mins) // 2], maxs[len(maxs) // 2]


def main():
    d = sd.ScopeDual(verbose=False)
    if not d.hw:
        print("hw 打不开:", d.why)
        return 1

    ch = 0
    if len(sys.argv) >= 2:
        ch = 0 if sys.argv[1].upper() == "CH1" else 1
    if len(sys.argv) >= 3:
        v1, v2 = float(sys.argv[-2]), float(sys.argv[-1])
    else:
        v1 = v2 = None

    print("标定通道: CH%d" % (ch + 1))
    print("名义参数: zero=511.5 gain=1.0  K=%.8f V/LSB" % K)
    print()

    # 让采集跑起来
    d.set_acqmode(0)
    d.configure(triglev=512, pre=2048)

    pts = []
    for idx in (1, 2):
        if v1 is not None and idx == 1:
            known = v1
        elif v2 is not None and idx == 2:
            known = v2
        else:
            try:
                known = float(input("第 %d 点：把信号源设成多少伏？(例如 1.0) " % idx))
            except Exception:
                print("输入无效")
                return 1
        raw = input("   把信号源调到 %.4fV，稳定后按回车..." % known) if (v1 is None) else ""
        time.sleep(0.6)
        mn, mx = read_lsb(d, ch)
        if mn is None:
            print("   读不到数据")
            return 1
        # 直流用中点；交流用峰峰值 -> 这里两者都算，取中点作为"该直流电平"的码
        mid_lsb = (mn + mx) / 2.0
        print("   原始 LSB: min=%d max=%d 中点=%.2f  (pp=%d)"
              % (mn, mx, mid_lsb, mx - mn))
        pts.append((known, mid_lsb))

    (V1, L1), (V2, L2) = pts
    if abs(L2 - L1) < 5:
        print("!! 两个点的 ADC 码几乎一样，信号没变？")
        return 1
    B = (V2 - V1) / (L2 - L1)
    zero = L1 - V1 / B
    gain = B / K
    print()
    print("=== 标定结果 ===")
    print("  B    = %.8f V/LSB" % B)
    print("  zero = %.3f      (名义 511.5)" % zero)
    print("  gain = %.6f     (名义 1.0)" % gain)
    print()
    print("验算:")
    for V, L in pts:
        print("    真实 %.4fV -> 用新参数算得 %.4fV" % (V, (L - zero) * K * gain))
    print()
    print("把下面两行填进 scope_processing.py:")
    print("    CAL_ZERO = %.3f" % zero)
    print("    CAL_GAIN = %.6f" % gain)
    print("CAL_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
