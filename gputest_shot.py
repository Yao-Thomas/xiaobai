#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gputest_shot.py —— 在板子上【独立】跑一遍 GPU 测试台的逻辑, 并停在画面上等截图

不经过触摸, 直接把四个测试全跑一遍, 用来验证 apps_gpu.py 真的能用。
桌面要先停掉。
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui                                        # noqa: E402
import apps_gpu as A                               # noqa: E402

scr = fbui.Screen()
if getattr(scr, "yoff", 0) != 0:
    try:
        scr.pan(0)
    except Exception as e:
        print("pan(0) 失败:", e)

st = {"gf": None, "why": "", "log": [], "btns": [],
      "addr": "", "phys": getattr(scr, "phys", 0),
      "stride": getattr(scr, "stride", 0), "yoff_note": ""}

A.push(st, "正在探测 FPGA GPU ...")
gf, why = A.find(scr)
st["gf"] = gf
st["why"] = why
if gf:
    st["addr"] = why
    A.push(st, "找到 GPU @%s" % why, (160, 240, 180))
    A.push(st, "驱动: gpubatch (C 批量), 8 字节/拍")
else:
    A.push(st, "没找到 GPU: %s" % why, (250, 180, 120))

A.draw(scr, st)
scr.flush()

print("=== 填充 + 校验 ===")
A.test_fill(scr, st)
A.flush_log(scr, st)
print("=== 画线 ===")
A.test_line(scr, st)
A.flush_log(scr, st)
print("=== GPU vs CPU ===")
A.test_vs_cpu(scr, st)
A.flush_log(scr, st)
print("=== 寄存器 ===")
A.test_regs(st)
# 寄存器那 9 行占满日志区, 只留最后几条给截图看 -> 再补一条结论
A.push(st, "")
i = 0
A.flush_log(scr, st)

for _line, _col in st["log"]:
    print(_line)

print("SCREEN_READY")
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
