#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal_from_pairs.py —— 用「真实值 / 显示值」两组数据算出 zero/gain 并写入 scope_cal.json

用法（本地或板上都行）：
    python3 cal_from_pairs.py ch0 1.0 0.95 4.0 4.01
        ch0 = CH1，真实1.0V显示0.95V，真实4.0V显示4.01V

原理：
    显示值 = (lsb - 511.5) * K          (K = V_FULL/SAMPLE_MAX，名义映射)
 -> lsb = 显示值 / K + 511.5
    B    = (V2 - V1) / (lsb2 - lsb1)    真正的 V/LSB
    zero = lsb1 - V1 / B
    gain = B / K
"""
import json
import os
import sys

V_FULL = 10.0
SAMPLE_MAX = 1023
K = V_FULL / SAMPLE_MAX
CAL_FILE = "/home/zynq/ui/scope_cal.json"


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        return 1
    ch = sys.argv[1]
    v1r, v1d, v2r, v2d = (float(x) for x in sys.argv[2:6])

    lsb1 = v1d / K + 511.5
    lsb2 = v2d / K + 511.5
    if abs(lsb2 - lsb1) < 5:
        print("两点 ADC 码太接近，无法标定")
        return 1
    B = (v2r - v1r) / (lsb2 - lsb1)
    zero = lsb1 - v1r / B
    gain = B / K

    print("输入: %s  真实%.3fV显示%.3fV , 真实%.3fV显示%.3fV" % (ch, v1r, v1d, v2r, v2d))
    print("  lsb1 = %.3f   lsb2 = %.3f" % (lsb1, lsb2))
    print("  B    = %.8f V/LSB" % B)
    print("  zero = %.3f" % zero)
    print("  gain = %.6f" % gain)
    print("验算:")
    for vr, vd, L in ((v1r, v1d, lsb1), (v2r, v2d, lsb2)):
        print("    真实 %.4fV -> 新参数算得 %.4fV   (原来显示 %.4fV)" %
              (vr, (L - zero) * K * gain, vd))

    data = {}
    try:
        if os.path.exists(CAL_FILE):
            with open(CAL_FILE) as f:
                data = json.load(f)
    except Exception:
        data = {}
    data[ch] = {"zero": round(zero, 4), "gain": round(gain, 6)}
    try:
        with open(CAL_FILE, "w") as f:
            json.dump(data, f, indent=2)
        os.system("sync")
        print("\n已写入 %s:" % CAL_FILE)
        print(json.dumps(data, indent=2))
    except Exception as e:
        print("\n写 %s 失败(%s)，请手工填写:" % (CAL_FILE, e))
        print('    {"%s": {"zero": %.4f, "gain": %.6f}}' % (ch, zero, gain))
    return 0


if __name__ == "__main__":
    sys.exit(main())
