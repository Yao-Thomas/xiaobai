#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_overrange_ui.py —— 验证「过量程提示」的完整显示链路（阶段3 bug⑦ / 阶段10）

不需要信号发生器：造一个饱和帧 -> 走 UI 的测量转换 -> 检查
  ① 模型里的 over 标志是否被置起
  ② draw_stat 是否把「过量程」文字用告警色画出来
  ③ draw_top 顶栏是否出现过量程告警
用像素比对（告警色出现次数）作为客观证据，不靠肉眼。

★ 离屏：flush 打桩，不写 /dev/fb0，桌面不受影响。
"""
import ctypes
import sys

sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch
import apps_scope_dual as A

C_WARN = A.C_WARN


def count_color(img, box, rgb, tol=12):
    """统计 box 区域内接近 rgb 的像素数"""
    sub = img.crop(box)
    px = sub.load()
    w, h = sub.size
    n = 0
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if (abs(p[0] - rgb[0]) <= tol and abs(p[1] - rgb[1]) <= tol
                    and abs(p[2] - rgb[2]) <= tol):
                n += 1
    return n


scr = Screen()
scr.flush = lambda box=None: None
touch = Touch()
app = A.App(scr)
app.make_bg()
for _ in range(40):
    app.step()

print("=== 1. 造饱和帧并走 C 检测 ===")
N = 4096
sig = [0 if ((i // 256) % 2) == 0 else 1023 for i in range(N)]
arr = (ctypes.c_ushort * N)(*sig)
so = (ctypes.c_int * 5)()
app.hw.lib.sd_saturation(arr, ctypes.c_int(N), so)
print("  贴0=%d 贴1023=%d 最长连续=%d -> 过量程=%s"
      % (so[0], so[1], max(so[2], so[3]), bool(so[4])))
assert so[4], "饱和帧竟未被判过量程"
print("  [OK] C 检测判定为过量程")

print()
print("=== 2. 把 over 标志灌进模型，看显示 ===")
app.m.m[0]["over"] = True
app.m.m[0]["vpp"] = 10.0
app.m.m[1]["over"] = False

# 基线：先画一次"不过量程"，数告警色
app.m.m[0]["over"] = False
app.m.active = 0
app.draw_stat()
app.draw_top()
n_before = count_color(app.scr.img, (0, A.ST1[1], A.W, A.ST1[3]), C_WARN)
n_top_before = count_color(app.scr.img, (0, 0, A.W, A.TOP_H), C_WARN)

# 过量程：再画
app.m.m[0]["over"] = True
app.draw_stat()
app.draw_top()
n_after = count_color(app.scr.img, (0, A.ST1[1], A.W, A.ST1[3]), C_WARN)
n_top_after = count_color(app.scr.img, (0, 0, A.W, A.TOP_H), C_WARN)

print("  参数行告警色像素: 正常=%d -> 过量程=%d" % (n_before, n_after))
print("  顶栏告警色像素  : 正常=%d -> 过量程=%d" % (n_top_before, n_top_after))
print("  参数行显示过量程: %s" % ("OK" if n_after > n_before + 50 else "FAIL 没画出来"))
print("  顶栏显示过量程  : %s" % ("OK" if n_top_after > n_top_before + 20 else "FAIL 没画出来"))

print()
print("=== 3. 确认 CH2 的过量程不会串到 CH1 ===")
# ★ 先把两个通道都设为【显示中】——否则未显示的通道会用暗灰色画文字
#   （这是设计行为：没显示的通道不需要抢眼）
app.m.ch[0].enabled = True
app.m.ch[1].enabled = True
app.m.m[0]["over"] = False
app.m.m[1]["over"] = True
app.draw_stat()
n1 = count_color(app.scr.img, (0, A.ST1[1], A.W, A.ST1[3]), C_WARN)
n2 = count_color(app.scr.img, (0, A.ST2[1], A.W, A.ST2[3]), C_WARN)
print("  CH1 行告警像素=%d   CH2 行告警像素=%d" % (n1, n2))
print("  通道分离: %s" % ("OK" if n2 > n1 + 50 else "FAIL 串了"))

print()
print("=== 4. 恢复正常后告警应消失 ===")
app.m.m[0]["over"] = False
app.m.m[1]["over"] = False
app.draw_stat()
n0 = count_color(app.scr.img, (0, A.ST1[1], A.W, A.ST1[3]), C_WARN)
n0b = count_color(app.scr.img, (0, A.ST2[1], A.W, A.ST2[3]), C_WARN)
print("  恢复正常后 CH1=%d CH2=%d -> %s"
      % (n0, n0b, "OK" if n0 < 20 and n0b < 20 else "FAIL 残留"))
print()
print("OVERRANGE_UI_DONE")
