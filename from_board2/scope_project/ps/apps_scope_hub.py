#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""示波器入口（服务卡片页）

点开后显示两个服务卡片：
  · 单通道示波器  -> apps_scope.run()       （原版，scope_cap @0x43CC0000）
  · 双通道示波器  -> apps_scope_dual.run()  （新版，scope_dual @0x43CF0000）

★ 只用 fbui.Screen 里【确定存在且参数简单】的 API：clear / rect / rrect / text / flush
  （不用 line —— 它的参数签名和 PIL 的不一样，实测会 TypeError）
"""
import time
from fbui import hit, back_hit

W, H = 1024, 600
TOP_H = 40

C_BG     = (12, 16, 32)
C_CARD   = (28, 38, 58)
C_CARD_H = (46, 66, 98)
C_TITLE  = (210, 228, 255)
C_SUB    = (140, 165, 200)
C_CH1    = (60, 180, 150)
C_CH2    = (235, 150, 60)
C_AI     = (165, 120, 235)

CW, CH = 300, 300
GAP = 30
Y0 = 152
_X0 = (W - (3 * CW + 2 * GAP)) // 2
CARD1 = [_X0, Y0, _X0 + CW, Y0 + CH]
CARD2 = [_X0 + CW + GAP, Y0, _X0 + 2 * CW + GAP, Y0 + CH]
CARD3 = [_X0 + 2 * (CW + GAP), Y0, _X0 + 3 * CW + 2 * GAP, Y0 + CH]


def _icon(scr, cx, cy, s, col, dual):
    """用矩形拼一个「示波器」图标（不用 line，保证 API 兼容）"""
    w = int(s * 0.80)
    h = int(s * 0.58)
    x0, y0 = cx - w // 2, cy - h // 2
    # 外框
    scr.rrect([x0, y0, x0 + w, y0 + h], 6, fill=(10, 20, 26), outline=col, width=3)
    # 网格（竖 3 条 + 横 2 条，用细矩形代替线）
    for i in range(1, 4):
        xx = x0 + i * (w // 4) - 1
        scr.rect([xx, y0 + 6, xx + 2, y0 + h - 6], fill=(28, 52, 52))
    for j in range(1, 3):
        yy = y0 + j * (h // 3) - 1
        scr.rect([x0 + 6, yy, x0 + w - 6, yy + 2], fill=(28, 52, 52))
    # 波形：用一排小方块拼出正弦的"点阵"
    import math
    n = 26
    for k in range(n):
        t = k / float(n - 1)
        px = x0 + 8 + int((w - 16) * t)
        py = int(cy + (h * 0.24) * math.sin(2 * math.pi * (t * 1.6)))
        if dual:
            py += int(h * 0.16)
        scr.rect([px, py - 2, px + 3, py + 2], fill=col)
        if dual:
            py2 = int(cy - (h * 0.18) * math.sin(2 * math.pi * (t * 1.6 + 0.18))) - int(h * 0.16)
            scr.rect([px, py2 - 2, px + 3, py2 + 2], fill=(255, 200, 70))


def _draw_page(scr, pressed=None):
    scr.clear(C_BG)
    scr.rect([0, 0, W, TOP_H], fill=(18, 24, 40))
    scr.text((20, TOP_H // 2), "示波器", 20, C_TITLE, anchor="lm", cn=True)
    scr.text((W - 16, TOP_H // 2), "选择服务", 15, C_SUB, anchor="rm", cn=True)

    cards = [
        (CARD1, "单通道示波器", "原版 · 1 路 10 位", C_CH1, False, "apps_scope"),
        (CARD2, "双通道示波器", "新版 · 2 路 · 20MS/s", C_CH2, True, "apps_scope_dual"),
        (CARD3, "AI 波形识别", "PL CNN · 8 类自动判别", C_AI, True, "apps_wave_ai"),
    ]
    for r, title, sub, col, dual, mod in cards:
        is_p = (pressed == mod)
        fill = C_CARD_H if is_p else C_CARD
        scr.rrect([r[0] + 3, r[1] + 4, r[2] + 3, r[3] + 4], 14, fill=(8, 11, 20))
        scr.rrect(r, 14, fill=fill, outline=col, width=3 if is_p else 2)
        _icon(scr, (r[0] + r[2]) // 2, r[1] + 106, 130, col, dual)
        scr.text(((r[0] + r[2]) // 2, r[3] - 82), title, 22, C_TITLE,
                 anchor="mm", cn=True)
        scr.text(((r[0] + r[2]) // 2, r[3] - 46), sub, 14, C_SUB,
                 anchor="mm", cn=True)

    scr.text((W // 2, H - 26), "点左上角方块返回桌面", 15, (110, 130, 165),
             anchor="mm", cn=True)
    scr.flush()


def run(scr, touch):
    """入口页主循环。

    ★ 关键：不要依赖 kind == "up"。
      desktop 的 Touch 在不同实现下可能返回 (x, y) 两元组（无 kind），
      这时原来的代码会把 kind 当成 "down"，于是永远等不到 "up"，
      表现就是【点了卡片没反应】。
      现在：任何事件只要落点在卡片内就触发，并用 0.6s 冷却防止一次按压触发多次。
    """
    import time as _t
    _draw_page(scr)
    cd = 0.0
    while True:
        ev = touch.poll(move=True)
        if ev:
            x = y = 0
            kind = "down"
            if isinstance(ev, (list, tuple)):
                if len(ev) >= 3:
                    x, y = ev[1], ev[2]
                    kind = ev[3] if len(ev) > 3 else "down"
                elif len(ev) == 2:
                    x, y = ev
            now = _t.time()
            if kind == "move":
                pass
            elif kind != "up" and now < cd:
                pass                       # 冷却中，忽略
            elif x < 90 and y < TOP_H + 20:
                return                     # 左上角退出
            else:
                try:
                    if back_hit(x, y):
                        return
                except Exception:
                    pass
                if hit(CARD1, x, y):
                    cd = now + 0.6
                    _draw_page(scr, pressed="apps_scope")
                    _t.sleep(0.10)
                    import apps_scope
                    apps_scope.run(scr, touch)
                    _draw_page(scr)
                elif hit(CARD2, x, y):
                    cd = now + 0.6
                    _draw_page(scr, pressed="apps_scope_dual")
                    _t.sleep(0.10)
                    import apps_scope_dual
                    apps_scope_dual.run(scr, touch)
                    _draw_page(scr)
                elif hit(CARD3, x, y):
                    cd = now + 0.6
                    _draw_page(scr, pressed="apps_wave_ai")
                    _t.sleep(0.10)
                    import apps_wave_ai
                    apps_wave_ai.run(scr, touch)
                    _draw_page(scr)
        _t.sleep(0.02)
