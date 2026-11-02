#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preview.py —— 在电脑上预览桌面/应用界面 (不需要板子!)
  原理: 把 fbui.Screen 换成一个"只画到 PNG 不写显存"的假屏幕
用法: python preview.py [desktop|mines|calc|draw|files|term|sys|net|about|gpu|all]
"""
import sys, os
from PIL import Image, ImageDraw

UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, UI)
import fbui


class FakeScreen(fbui.Screen):
    """假屏幕: 不碰 /dev/fb0, 只画到内存图像"""
    def __init__(self):
        self.w, self.h, self.vh = 1024, 600, 1200
        self.bpp, self.bppx, self.stride = 24, 3, 3072
        self.phys = 0
        self.gpu = None
        self.mode = "BGR;24"
        self._fast = True
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ImageDraw.Draw(self.img)

    def flush(self, box=None):
        pass


class FakeTouch:
    def __init__(self, taps=None):
        self.taps = list(taps or [])
    def poll(self, move=False):
        return None


fbui.Screen = FakeScreen


def save(scr, name):
    out = os.path.join(os.path.dirname(UI), "预览_%s.png" % name)
    scr.img.save(out)
    print("  -> %s" % out)
    return out


def preview_desktop():
    import desktop
    desktop.Screen = FakeScreen
    desktop.Touch = FakeTouch
    d = desktop.Desktop.__new__(desktop.Desktop)   # 跳过 __init__(避免碰真设备)
    d.scr = FakeScreen()
    d.touch = FakeTouch()
    d.apps = list(desktop.APPS)
    d.menu_open = False
    d.last_clock = ""
    d.cpu = 7
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
    save(d.scr, "桌面")
    # 开始菜单打开的样子
    d.menu_open = True
    d.draw()
    save(d.scr, "桌面_开始菜单")
    # 按下反馈
    d.menu_open = False
    d.draw(pressed="GPU 加速")
    save(d.scr, "桌面_按下反馈")
    # 拖动中的样子
    d.drag = d.apps[2]
    d.drag_pos = (620, 300)
    d.draw()
    save(d.scr, "桌面_拖动图标")
    d.drag = None


def preview_mines():
    import apps_mines as m
    scr = FakeScreen()
    g = m.Game()
    for c, r in [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1)]:
        if (c, r) not in g.mine:
            g.tap(c, r)
    g.flag.add((9, 5))
    g.flag.add((8, 5))
    m.draw(scr, g)
    save(scr, "扫雷")


def preview_calc():
    import apps_calc as a
    scr = FakeScreen()
    a.draw(scr, "1234+567", 1801, "")
    save(scr, "计算器")


def preview_draw():
    import apps_draw as a
    scr = FakeScreen()
    from PIL import ImageDraw
    a.run.__globals__  # noqa
    # 直接构造一次画面
    scr.clear((16, 20, 36))
    fbui.header(scr, "画板")
    cv = [52, 68, 972, 504]
    scr.d.rectangle(cv, fill=(252, 252, 255), outline=(90, 110, 150), width=2)
    cols, szs, others = a.toolbar()
    for kind, c, r in cols:
        fbui.btn(scr, r, "", fill=c, radius=8, outline=(255, 255, 255) if c == a.COLORS[1][1] else (70, 80, 110))
    for kind, s, r in szs:
        fbui.btn(scr, r, "", fill=(200, 200, 210), radius=8, outline=(90, 200, 255) if s == 8 else (70, 80, 110))
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        scr.d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(30, 34, 48))
    fbui.btn(scr, others[0][1], "清空", fill=(150, 60, 60), size=22, cn=True)
    fbui.btn(scr, others[1][1], "保存", fill=(46, 130, 200), size=22, cn=True)
    # 画几笔
    import math
    for t in range(0, 360, 4):
        x = 500 + int(160 * math.cos(math.radians(t)))
        y = 280 + int(120 * math.sin(math.radians(t * 3)))
        scr.d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(220, 50, 50))
    save(scr, "画板")


def preview_term():
    import apps_term as a
    scr = FakeScreen()
    t = a.Term()
    t.lines = ["Zynq 命令面板 —— 点下面按钮或打字后按回车",
               "$ uname -a",
               "Linux zynq-board 5.4.0-xilinx-v2020.2 #1 SMP PREEMPT armv7l GNU/Linux",
               "$ df -h /",
               "Filesystem      Size  Used Avail Use% Mounted on",
               "/dev/root        29G  1.1G   27G   4% /",
               "$ free -m",
               "              total   used   free",
               "Mem:           1004    180    620"]
    t.cur = "ls -l /home"
    t.draw(scr)
    save(scr, "命令面板")


def preview_gpu():
    import apps_gpu as a
    scr = FakeScreen()
    st = {"gpu": None, "log": [
        "正在查找 FPGA GPU ...",
        "未找到 GPU (bitstream 未集成)",
        "下面按钮会回退到软件渲染",
        "[集成后这里会显示]",
        "  找到 GPU @0x43C10000 ✅",
        "  填充 #E03030 -> 24000 像素, 0.8 ms ✅",
        "  硬件(GPU): 1.9 ms  (614400 像素)",
        "  ★ 加速比: 180.5 倍",
    ], "btns": [], "err": ""}
    a.draw(scr, st)
    save(scr, "GPU加速")


def preview_about():
    import apps_about as a
    scr = FakeScreen()
    a.draw(scr)
    save(scr, "关于")


def preview_sys():
    import apps_sys as a
    scr = FakeScreen()
    extra = {"kernel": "5.4.0-xilinx-v2020.2", "host": "zynq-board",
             "uptime": "3 时 42 分", "dused": "1.1G", "dtotal": "29.0G",
             "dpct": 4, "wlan": "wlx688fc92bd646", "ip": "192.168.43.210",
             "temp": "48.3 C"}
    a.draw(scr, 7, {"total": 1004, "used": 186, "pct": 19}, extra)
    save(scr, "系统信息")


def preview_net():
    import apps_net as a
    scr = FakeScreen()
    a.draw(scr, ("wlx688fc92bd646", "192.168.43.210", "192.168.43.1",
                 "68:8f:c9:2b:d6:46", "001", "-42 dBm"),
           "成功: 2/2 包, 网络正常")
    save(scr, "网络")


def preview_view():
    import apps_view as a
    scr = FakeScreen()
    files = ["/home/zynq/Pictures/draw_0919_123456.png",
             "/home/zynq/Pictures/draw_0919_123530.png",
             "/home/zynq/Pictures/photo1.jpg",
             "/home/zynq/Pictures/screenshot.png",
             "/home/zynq/ui/test_ui.py.png"]
    a.list_view(scr, files, 0)
    save(scr, "图片查看器")


ALL = {
    "desktop": preview_desktop, "mines": preview_mines, "calc": preview_calc,
    "draw": preview_draw, "term": preview_term, "gpu": preview_gpu,
    "about": preview_about, "sys": preview_sys, "net": preview_net,
    "view": preview_view,
}

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    todo = ALL.keys() if which == "all" else [which]
    for k in todo:
        if k in ALL:
            print("[预览] %s" % k)
            try:
                ALL[k]()
            except Exception as ex:
                import traceback
                print("  失败: %s" % ex)
                traceback.print_exc()
    print("完成")
