#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_mines.py —— 桌面版扫雷(触摸)"""
import random, time
from PIL import ImageDraw

COLS, ROWS, MINES = 10, 6, 10
TOP = 64
MARGIN = 12
NUMC = [None, (30, 90, 200), (36, 140, 60), (210, 50, 50), (120, 40, 180),
        (230, 120, 20), (0, 140, 150), (69, 69, 69), (20, 20, 20)]


class Game:
    def __init__(self):
        self.flag_mode = False
        self.reset()

    def reset(self):
        allc = [(c, r) for c in range(COLS) for r in range(ROWS)]
        self.mine = set(random.sample(allc, MINES))
        self.open, self.flag = set(), set()
        self.boom, self.state = None, "play"

    def nbrs(self, c, r):
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if (dc or dr) and 0 <= c + dc < COLS and 0 <= r + dr < ROWS:
                    yield c + dc, r + dr

    def cnt(self, c, r):
        return sum(1 for n in self.nbrs(c, r) if n in self.mine)

    def tap(self, c, r):
        if self.state != "play" or not (0 <= c < COLS and 0 <= r < ROWS):
            return
        if self.flag_mode:
            if (c, r) in self.flag:
                self.flag.discard((c, r))
            elif (c, r) not in self.open:
                self.flag.add((c, r))
            return
        if (c, r) in self.flag or (c, r) in self.open:
            return
        if (c, r) in self.mine:
            self.boom, self.state = (c, r), "lose"
            return
        st = [(c, r)]
        while st:
            cc, rr = st.pop()
            if (cc, rr) in self.open or (cc, rr) in self.flag:
                continue
            self.open.add((cc, rr))
            if self.cnt(cc, rr) == 0:
                for n in self.nbrs(cc, rr):
                    if n not in self.open:
                        st.append(n)
        if len(self.open) == COLS * ROWS - MINES:
            self.state = "win"


def layout(scr):
    cw = (scr.w - 2 * MARGIN) // COLS
    ch = (scr.h - TOP - 2 * MARGIN) // ROWS
    ox = (scr.w - cw * COLS) // 2
    oy = TOP + (scr.h - TOP - ch * ROWS) // 2
    return cw, ch, ox, oy


def buttons(scr):
    """返回 (返回钮, 模式钮, 重开钮) 的矩形"""
    back = (10, 10, 130, 54)
    mode = (scr.w // 2 - 110, 10, scr.w // 2 + 110, 54)
    new = (scr.w - 150, 10, scr.w - 10, 54)
    return back, mode, new


def draw(scr, g):
    cw, ch, ox, oy = layout(scr)
    back, mode, new = buttons(scr)
    # 背景
    scr.clear((24, 24, 24))
    scr.rect([0, 0, scr.w, TOP - 4], fill=(40, 40, 40))
    scr.rect([0, TOP - 4, scr.w, TOP], fill=(70, 110, 180))

    # 返回
    scr.rrect(list(back), 10, fill=(60, 70, 100))
    scr.text((70, 32), "< 返回", 22, (255, 255, 255), cn=True, anchor="mm")
    # 模式
    on = g.flag_mode
    scr.rrect(list(mode), 10, fill=(46, 158, 79) if on else (138, 107, 58))
    scr.text((scr.w // 2, 32), "插旗模式" if on else "挖开模式", 22,
             (255, 255, 255), cn=True, anchor="mm")
    # 重开
    scr.rrect(list(new), 10, fill=(158, 46, 46))
    scr.text((scr.w - 80, 32), "重开", 22, (255, 255, 255), cn=True, anchor="mm")
    # 剩余雷数
    scr.text((scr.w - 300, 32), "剩余 %d" % max(0, MINES - len(g.flag)), 22,
             (255, 213, 79), cn=True, anchor="rm")

    # 棋盘
    for r in range(ROWS):
        for c in range(COLS):
            x, y = ox + c * cw, oy + r * ch
            if (c, r) in g.open:
                scr.rect([x + 1, y + 1, x + cw - 2, y + ch - 2], fill=(204, 204, 204))
                n = g.cnt(c, r)
                if n:
                    scr.text((x + cw // 2, y + ch // 2), str(n), 40, NUMC[n], bold=True, anchor="mm")
            else:
                scr.rrect([x + 1, y + 1, x + cw - 2, y + ch - 2], 8, fill=(62, 92, 118))
                scr.rrect([x + 5, y + 5, x + cw - 6, y + 12], 4, fill=(102, 136, 170))
                if (c, r) in g.flag:
                    scr.d.ellipse([x + cw // 2 - 26, y + ch // 2 - 26,
                                   x + cw // 2 + 26, y + ch // 2 + 26], fill=(240, 160, 32))
                    scr.d.ellipse([x + cw // 2 - 14, y + ch // 2 - 14,
                                   x + cw // 2 + 14, y + ch // 2 + 14], fill=(255, 220, 140))
            if g.state == "lose" and (c, r) in g.mine:
                col = (255, 48, 48) if (c, r) == g.boom else (139, 32, 32)
                scr.d.ellipse([x + cw // 2 - 26, y + ch // 2 - 26,
                               x + cw // 2 + 26, y + ch // 2 + 26], fill=col)

    if g.state in ("win", "lose"):
        msg = "全部扫清!" if g.state == "win" else "踩雷了!"
        col = (105, 240, 174) if g.state == "win" else (255, 82, 82)
        scr.rrect([scr.w // 2 - 210, scr.h // 2 - 70, scr.w // 2 + 210, scr.h // 2 + 60], 18,
                  fill=(0, 0, 0))
        scr.text((scr.w // 2, scr.h // 2 - 20), msg, 46, col, cn=True, bold=True, anchor="mm")
        scr.text((scr.w // 2, scr.h // 2 + 30), "点“重开”再来一局", 22, (200, 200, 200),
                 cn=True, anchor="mm")


def run(scr, touch):
    g = Game()
    print("扫雷: 开始")
    while True:
        draw(scr, g)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            back, mode, new = buttons(scr)
            if back[0] <= x <= back[2] and back[1] <= y <= back[3]:
                print("扫雷: 返回")
                return
            if mode[0] <= x <= mode[2] and mode[1] <= y <= mode[3]:
                g.flag_mode = not g.flag_mode
            elif new[0] <= x <= new[2] and new[1] <= y <= new[3]:
                g.reset()
            else:
                cw, ch, ox, oy = layout(scr)
                if y >= TOP:
                    g.tap((x - ox) // cw, (y - oy) // ch)
            print("  扫雷 tap", x, y, "->", g.state)
        time.sleep(0.02)
