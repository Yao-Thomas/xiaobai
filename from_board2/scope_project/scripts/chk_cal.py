#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chk_cal.py —— 确认板上读到的标定值"""
import sys

sys.path.insert(0, "/home/zynq/ui")
from scope_processing import ChannelCal, CAL, CAL_ZERO, CAL_GAIN
from scope_model import ScopeModel

print("内置默认: CAL_ZERO=%.3f CAL_GAIN=%.6f" % (CAL_ZERO, CAL_GAIN))
print("读到标定文件 scope_cal.json:", CAL if CAL else "(不存在)")

c0, c1 = ChannelCal(0), ChannelCal(1)
print("CH1 zero=%.3f gain=%.6f   (期望 504.339 / 0.980392)" % (c0.zero, c0.gain))
print("CH2 zero=%.3f gain=%.6f   (期望 511.5 / 1.0 尚未标定)" % (c1.zero, c1.gain))

m = ScopeModel()
print("模型构造 OK")
print("CH1 to_volt(608.685) = %.4f V   (真实 1.000V)" % m.ch[0].to_volt(608.685))
print("CH1 to_volt(921.723) = %.4f V   (真实 4.000V)" % m.ch[0].to_volt(921.723))
print("CH2 to_volt(608.685) = %.4f V" % m.ch[1].to_volt(608.685))
print("CHK_CAL_DONE")
