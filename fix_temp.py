#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_temp.py —— 修 /status 里的温度换算

原代码：
    for p in (...):
        raw = int(open(p).read())
        d["temp"] = (raw/1000.0 if raw > 2000 else <XADC公式>)

bug：那个 "raw > 2000 就 /1000" 是给 /sys/class/thermal/thermal_zone0/temp
     的 millidegree 格式写的。但这块板子**没有 thermal_zone**，只有 XADC，
     而 XADC 的 raw 也是四位数（2886），于是被误判 -> 显示 2.9 °C。

正确做法：优先用 IIO 的标准属性 (raw + offset) * scale（scale 是毫度，再 /1000）。

实测（2026-09-28）：
    raw=2886  offset=-2219  scale=123.04
    (2886-2219)*123.04/1000 = 82.1 C
    与 Zynq 通用公式 raw*503.975/4096-273.15 = 81.9 C 吻合 ✓
"""
import io
import re
import sys

P = "agent/main.py"
src = io.open(P, encoding="utf-8").read()

if "in_temp0_offset" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# 找到原来的温度那段（在 _sysinfo 里）
m = re.search(r"        # ★ 温度：.*?\n(?:.*?\n)*?            pass\n", src)
if not m:
    # 退一步：找含 thermal_zone 的块
    m = re.search(
        r"        for p in \(\"/sys/class/thermal.*?\n(?:.*?\n)*?"
        r"                pass\n", src)
if not m:
    print("  [!] 没找到温度那段，手工确认")
    sys.exit(1)

NEW = '''        # ★ 温度：这块板子**没有 thermal_zone**，只有 XADC。
        #   优先用 IIO 的标准属性 (raw + offset) * scale（scale 单位是毫度）。
        #   踩过的坑：原来写"raw > 2000 就 /1000"（那是给 millidegree 格式的），
        #   而 XADC 的 raw 也是四位数（2886），被误判成 2.9 °C。
        _xd = "/sys/devices/soc0/amba/f8007100.adc/iio:device0"
        try:
            _r = float(open(_xd + "/in_temp0_raw").read())
            _o = float(open(_xd + "/in_temp0_offset").read())
            _s = float(open(_xd + "/in_temp0_scale").read())
            d["temp"] = round((_r + _o) * _s / 1000.0, 1)
            d["temp_src"] = "xadc"
        except Exception:
            for p in ("/sys/class/thermal/thermal_zone0/temp",
                      "/sys/class/hwmon/hwmon0/temp1_input"):
                try:
                    raw = int(open(p).read().strip())
                    d["temp"] = round(raw / 1000.0, 1)
                    d["temp_src"] = p.split("/")[-2]
                    break
                except Exception:
                    continue
'''

src = src[:m.start()] + NEW + src[m.end():]
io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
