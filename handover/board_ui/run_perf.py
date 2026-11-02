#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_perf.py —— 在板子上跑 GPU 卸载对比实验(不经过桌面)

不带参数: 交互跑       带参数: 自动跑完一组负载档位再退出
"""
import sys
import time
import traceback

sys.path.insert(0, "/home/zynq/ui")
import fbui
import apps_gpuperf as A


def main():
    scr = fbui.Screen()
    touch = fbui.Touch()
    print("PERF START", flush=True)
    auto = len(sys.argv) > 1 and sys.argv[1] == "auto"
    if not auto:
        try:
            A.run(scr, touch)
            print("PERF RETURNED ok", flush=True)
        except Exception:
            traceback.print_exc()
        return

    # 自动模式: 逐个负载档位 x 两种模式, 各跑 6 秒, 收集 FPS
    p = A.Perf(scr, touch)
    import ctypes
    from PIL import Image, ImageDraw
    print("%-8s %-6s %-8s %-10s %-10s" % ("模式", "负载", "FPS", "画图ms", "计算ms"))
    for mode in (0, 1):
        for li in range(len(A.LOADS)):
            p.mode = mode
            p.load = li
            p.fps = 0.0
            n = 0
            t0 = time.time()
            s_draw = s_calc = 0.0
            while time.time() - t0 < 6.0:
                ta = time.time()
                if mode == 0 and p.hw:
                    p.draw_gpu()
                else:
                    p.draw_cpu()
                tb = time.time()
                p.step()
                tc = time.time()
                if mode == 0 and p.hw:
                    p.gf.sync()
                p.finish_draw(mode == 0 and p.hw)
                n += 1
                s_draw += (tb - ta) * 1000.0
                s_calc += (tc - tb) * 1000.0
            el = time.time() - t0
            print("%-8s %-6d %-8.1f %-10.2f %-10.2f"
                  % ("GPU" if (mode == 0 and p.hw) else "CPU",
                     A.LOADS[li], n / el, s_draw / max(1, n), s_calc / max(1, n)),
                  flush=True)
    print("PERF DONE", flush=True)


main()
