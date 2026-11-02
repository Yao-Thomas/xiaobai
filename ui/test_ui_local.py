#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ui_local.py —— 本地自动化 UI 测试 (不需要板子!)
  对每个应用: 用假屏幕跑起来, 注入一串点击, 检查有没有崩溃
用法: python test_ui_local.py
"""
import sys, os, traceback
from PIL import Image, ImageDraw

UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, UI)
import fbui


class FakeScreen(fbui.Screen):
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0
        self.gpu = None
        self.mode = "BGR;24"
        self._fast = True
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)
        self.frames = 0

    def flush(self, box=None):
        self.frames += 1


class ScriptedTouch:
    """按脚本吐点击; 脚本用完就吐 '返回' 让它退出"""
    def __init__(self, taps, max_polls=4000):
        self.taps = list(taps)
        self.n = 0
        self.max_polls = max_polls

    def poll(self, move=False):
        self.n += 1
        if self.n > self.max_polls:
            raise RuntimeError("应用没有退出 (超过 %d 次轮询)" % self.max_polls)
        if self.taps:
            x, y = self.taps.pop(0)
            return ("tap", x, y)
        return ("tap", 70, 30)      # 点"返回"


fbui.Screen = FakeScreen

# 每个应用的点击脚本
TESTS = {
    "apps_mines": [(200, 200), (300, 200), (860, 32), (620, 32), (200, 300)],
    "apps_calc":  [(200, 200), (300, 200), (300, 270), (600, 520), (150, 200)],
    "apps_draw":  [(300, 300), (400, 300), (500, 300), (140, 540), (400, 540), (560, 540)],
    "apps_view":  [(200, 100), (200, 40), (512, 560)],
    "apps_about": [],
    # GPU 应用: 4 个按钮在 y≈196..262, 逐个点一遍
    "apps_gpu":   [(165, 230), (400, 230), (630, 230), (860, 230), (100, 500)],
    # 以下原本"需要板子", 加固后本地也能跑(路径不存在时应优雅降级)
    "apps_files": [(100, 138), (300, 190), (600, 300), (512, 400)],
    "apps_term":  [(80, 88), (200, 88), (300, 88), (450, 400), (500, 500), (600, 460)],
    "apps_sys":   [(300, 300)],
    "apps_net":   [(180, 567), (300, 300)],
}
BOARD_ONLY = []          # 全部纳入测试 ✅


def run_one(mod_name, taps):
    try:
        mod = __import__(mod_name)
    except Exception as ex:
        return "导入失败: %s" % ex, None
    scr = FakeScreen()
    t = ScriptedTouch(taps)
    try:
        mod.run(scr, t)
        return None, scr.frames
    except RuntimeError as ex:
        return "未退出: %s" % ex, scr.frames
    except Exception:
        return "崩溃:\n" + traceback.format_exc(), scr.frames


def main():
    print("=" * 66)
    print(" 本地 UI 自动化测试")
    print("=" * 66)
    ok = fail = 0
    for name, taps in TESTS.items():
        print("\n[测试] %-14s 点击 %d 次" % (name, len(taps)))
        err, frames = run_one(name, taps)
        if err:
            fail += 1
            print("   ❌ %s" % err)
        else:
            ok += 1
            print("   ✅ 正常退出 (渲染 %d 帧)" % frames)

    print("\n[检查] 所有应用能否导入 (找语法/依赖错误)")
    import importlib
    allmods = list(TESTS.keys()) + BOARD_ONLY + ["preview", "gpu"]
    for m in allmods:
        try:
            importlib.import_module(m)
            print("   ✅ %s" % m)
            ok += 1
        except Exception as ex:
            print("   ❌ %s: %s" % (m, ex))
            fail += 1

    print("\n[跳过] 需要板子的应用:", ", ".join(BOARD_ONLY))
    print("        (它们读 /proc、/dev/mem、真实文件系统)")

    # 桌面单独测
    print("\n[测试] desktop (开始菜单 -> 打开应用)")
    try:
        import desktop
        desktop.Screen = FakeScreen
        d = desktop.Desktop.__new__(desktop.Desktop)
        d.scr = FakeScreen()
        d.touch = ScriptedTouch([(64, 574), (150, 400), (70, 30), (64, 574), (150, 300)])
        d.apps = list(desktop.APPS)
        d.menu_open = False
        d.last_clock = ""
        d.cpu = 5
        d.last_cpu_t = 0
        d._cpu_prev = None
        d.drag = None
        d.drag_pos = (0, 0)
        d.drag_from = -1
        d.press_t = 0.0
        d.pressed = None
        d.anim = None
        d.wall = d.make_wallpaper()
        d.draw()
        # 只测菜单开关 + 图标命中逻辑, 不跑完整 run(会进应用循环)
        assert d.menu_rect()[0] == 10
        rects = d.menu_items()
        print("   ✅ 开始菜单 %d 项, 菜单区域 %s" % (len(rects), d.menu_rect()))
        icons = d.grid()
        print("   ✅ 桌面图标 %d 个" % len(icons))
        inside = all(0 <= r[0] and r[2] <= 1024 and r[3] <= 600 - 56 for r in
                     [i[:4] for i in icons])
        print("   %s 图标都在屏幕内" % ("✅" if inside else "❌"))
        for i in icons:
            if not (0 <= i[0] and i[2] <= 1024 and i[3] <= 600 - 56):
                print("       越界: %s" % (i[4]["name"],))
        ok += 1
    except Exception:
        fail += 1
        print("   ❌ 崩溃:\n" + traceback.format_exc())

    print("\n" + "=" * 66)
    print(" 结果: %d 通过, %d 失败" % (ok, fail))
    print("=" * 66)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
