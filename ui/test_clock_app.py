#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_clock_app.py —— 脱离桌面，单独测 apps_clock 的四个表盘能不能画

用一个假的 scr（包一层 PIL Image），不碰真实 framebuffer，
这样能直接抓出运行时错误，不用反复重启桌面。
"""
import math
import sys
import time
import traceback

from PIL import Image, ImageDraw

sys.path.insert(0, "/home/zynq/ui")


class FakeScr(object):
    """模仿 fbui.Screen 里 apps_clock 用到的那几个方法"""

    def __init__(self, w=1024, h=600):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w, h), (0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def clear(self, c=(0, 0, 0)):
        self.d.rectangle([0, 0, self.w, self.h], fill=c)

    def text(self, xy, s, size=20, fill=(255, 255, 255), bold=False,
             cn=False, anchor=None, mono=False):
        try:
            self.d.text(xy, s, fill=fill, anchor=anchor)
        except Exception:
            self.d.text(xy, s, fill=fill)

    def tw(self, s, size=20, bold=False, cn=False, mono=False):
        return int(len(str(s)) * size * 0.62)

    def rrect(self, xy, r, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(xy, radius=r, fill=fill,
                                 outline=outline, width=width)

    def rect(self, xy, fill=None, outline=None, width=1):
        self.d.rectangle(xy, fill=fill, outline=outline, width=width)

    def line(self, xy, fill=(255, 255, 255), width=1):
        self.d.line(xy, fill=fill, width=width)

    def flush(self, box=None):
        pass


def main():
    import apps_clock as C
    print("=" * 74)
    print("单独测 apps_clock（不动真实屏幕）")
    print("=" * 74)
    print("  模块来自:", C.__file__)
    print("  表盘:", C.FACES)
    print()

    scr = FakeScr()
    body = [0, 104, 1024, 500]
    now = time.time()
    sw = C.Stopwatch()

    tests = [
        ("数字", lambda: C.draw_digital(scr, now, body)),
        ("指针", lambda: C.draw_pointer(scr, now, body)),
        ("世界", lambda: C.draw_world(scr, now, body)),
        ("秒表", lambda: C.draw_stopwatch(scr, sw, body)),
    ]
    ok = 0
    for name, fn in tests:
        try:
            scr.clear((0, 0, 0))
            box = fn()
            print("  ✓ %-4s 画成功  返回包围盒=%s" % (name, box))
            ok += 1
        except Exception as e:
            print("  ✗ %-4s 失败: %s: %s" % (name, type(e).__name__, e))
            traceback.print_exc()
    print()
    print("  %d/%d 个表盘通过" % (ok, len(tests)))

    # 秒表逻辑
    print()
    print("  秒表逻辑:")
    sw.start()
    time.sleep(0.3)
    sw.stop()
    e1 = sw.elapsed()
    time.sleep(0.2)
    e2 = sw.elapsed()
    print("    停止后 elapsed 不再增长: %.2f -> %.2f  %s"
          % (e1, e2, "✓" if abs(e2 - e1) < 0.05 else "✗"))
    sw.reset()
    print("    复位后 elapsed = %.2f  %s" % (sw.elapsed(), "✓" if sw.elapsed() < 0.01 else "✗"))
    return 0 if ok == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
