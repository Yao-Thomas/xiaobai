#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_draw.py —— 触摸画板 (可保存 PNG)"""
import time, os, datetime
from fbui import header, back_hit, btn, hit

CANVAS = [52, 68, 972, 504]
COLORS = [
    ("黑", (20, 20, 24)), ("红", (220, 50, 50)), ("橙", (240, 140, 30)),
    ("黄", (240, 210, 50)), ("绿", (50, 190, 90)), ("蓝", (60, 130, 240)),
    ("紫", (160, 80, 220)), ("白", (245, 245, 250)),
]
SIZES = [3, 8, 16, 28]

def toolbar():
    """工具栏: 8 色 + 4 笔粗 + 清空 + 保存, 必须全部落在 1024 宽度内
       52(左边距) + 8*58 + 16 + 4*58 + 16 + 220 = 52+464+16+232+16+220 = 1000 < 1024 ✅
    """
    y0, y1 = 514, 586
    SW, GAP = 52, 6
    rects = []
    x = 52
    for name, c in COLORS:
        rects.append(("color", c, [x, y0, x + SW, y1]))
        x += SW + GAP
    x += 16
    sz = []
    for s in SIZES:
        sz.append(("size", s, [x, y0, x + SW, y1]))
        x += SW + GAP
    x += 16
    others = [("清空", [x, y0, x + 104, y1]),
              ("保存", [x + 112, y0, x + 216, y1])]
    return rects, sz, others

def run(scr, touch):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (CANVAS[2] - CANVAS[0], CANVAS[3] - CANVAS[1]), (252, 252, 255))
    cd = ImageDraw.Draw(canvas)
    cur_color = (20, 20, 24)
    cur_size = 8
    last = None
    saved_msg = ""

    def redraw():
        scr.clear((16, 20, 36))
        header(scr, "画板")
        scr.img.paste(canvas, (CANVAS[0], CANVAS[1]))
        scr.d.rectangle(CANVAS, outline=(90, 110, 150), width=2)
        cols, szs, others = toolbar()
        for kind, c, r in cols:
            btn(scr, r, "", fill=c, radius=8,
                outline=(255, 255, 255) if c == cur_color else (70, 80, 110))
        for kind, s, r in szs:
            btn(scr, r, "", fill=(200, 200, 210), radius=8,
                outline=(90, 200, 255) if s == cur_size else (70, 80, 110))
            cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
            scr.d.ellipse([cx - s, cy - s, cx + s, cy + s], fill=(30, 34, 48))
        btn(scr, others[0][1], "清空", fill=(150, 60, 60), size=22, cn=True)
        btn(scr, others[1][1], "保存", fill=(46, 130, 200), size=22, cn=True)
        if saved_msg:
            scr.text((512, 604 - 8), saved_msg, 17, (130, 230, 180), cn=True, anchor="mb")

    redraw()
    scr.flush()

    down_xy = [None]          # 本次落笔的起点 (用于判断"点击"还是"拖动")

    def do_tap(x, y):
        """处理一次"点击"

        返回值: True = 要退出应用(点了「< 返回」)
                False = 只是操作了工具栏(换色/换笔/清空/保存), 继续留在画板
        """
        nonlocal cur_color, cur_size, saved_msg
        if back_hit(x, y):
            print("画板: 返回桌面", flush=True)
            return True                      # ★ 只有这里才退出
        cols, szs, others = toolbar()
        for k, c, r in cols:
            if hit(r, x, y):
                cur_color = c
                print("画板: 换颜色", c, flush=True)
                return False
        for k, s, r in szs:
            if hit(r, x, y):
                cur_size = s
                print("画板: 换笔粗", s, flush=True)
                return False
        if hit(others[0][1], x, y):
            cd.rectangle([0, 0, canvas.width, canvas.height], fill=(252, 252, 255))
            saved_msg = "已清空"
            print("画板: 清空", flush=True)
            return False
        if hit(others[1][1], x, y):
            d = "/home/zynq/Pictures"
            os.makedirs(d, exist_ok=True)
            fn = d + "/draw_" + datetime.datetime.now().strftime("%m%d_%H%M%S") + ".png"
            canvas.save(fn)
            saved_msg = "已保存: " + os.path.basename(fn)
            print("画板保存:", fn, flush=True)
            return False
        return False                         # 点了空白处, 什么都不做

    while True:
        # ★ 一次把系统攒下的事件全部处理掉, 最后只重绘一次。
        #   否则每个触摸采样都整屏重绘(30ms+), 事件越积越多 -> 笔画看起来断断续续/连错。
        dirty = False
        n = 0
        while n < 80:
            ev = touch.poll(move=True)
            if not ev:
                break
            n += 1
            kind, x, y = ev

            # ---- 落笔 ----
            if kind == "down":
                last = None
                down_xy[0] = (x, y)
                if hit(CANVAS, x, y):
                    px, py = x - CANVAS[0], y - CANVAS[1]
                    cd.ellipse([px - cur_size // 2, py - cur_size // 2,
                                px + cur_size // 2, py + cur_size // 2], fill=cur_color)
                    last = (px, py)
                    dirty = True
                continue

            # ---- 抬笔 ----
            # ★ 关键: move=True 时系统不会产生 'tap' 事件, 所以按钮点击必须在
            #   'up' 里自己判断 —— 落点和抬点接近(没怎么动) 且不在画布内 -> 算点击
            if kind == "up":
                if (down_xy[0] is not None and not hit(CANVAS, x, y)
                        and abs(x - down_xy[0][0]) < 30 and abs(y - down_xy[0][1]) < 30):
                    if do_tap(x, y):
                        return
                    dirty = True
                last = None
                down_xy[0] = None
                continue

            if kind == "move":
                if hit(CANVAS, x, y):
                    px, py = x - CANVAS[0], y - CANVAS[1]
                    if last:
                        cd.line([last, (px, py)], fill=cur_color, width=cur_size)
                    cd.ellipse([px - cur_size // 2, py - cur_size // 2,
                                px + cur_size // 2, py + cur_size // 2], fill=cur_color)
                    last = (px, py)
                    dirty = True
                elif last is not None:
                    last = None          # 手指划出画布 -> 断开
                continue

            # ---- tap (注入/其它路径可能给这个) ----
            last = None
            if do_tap(x, y):
                return
            if hit(CANVAS, x, y):
                dirty = True

        if dirty:
            redraw()
            scr.flush()
        else:
            time.sleep(0.01)

