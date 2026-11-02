#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fightlab.py —— 本地预览 死神VS火影 的角色帧和整体画面"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ui"))

import apps_fight as F   # noqa: E402


def frames_sheet():
    poses = ["idle", "idle2", "walk1", "walk2", "jump", "crouch",
             "atk_l_w", "atk_l", "atk_l_r", "atk_h_w", "atk_h", "atk_h_r",
             "special_w", "special", "special_r", "block", "hit", "down"]
    cols = 6
    rows = 2 * ((len(poses) + cols - 1) // cols)
    cw, ch = F.SW // 3, F.SH // 3
    sheet = Image.new("RGB", (cw * cols, ch * rows + 20 * rows), (30, 32, 40))
    d = ImageDraw.Draw(sheet)
    for ci in range(2):
        imgs = F.build_frames(ci)
        for k, p in enumerate(poses):
            r = ci * (len(poses) // cols) + k // cols
            c = k % cols
            # ★ build_frames 返回的是【按真实内容裁剪过】的图, 预览时要按
            #   记录的原点贴回完整画布, 否则每张的缩放基准都不一样
            full = Image.new("RGBA", (F.SW, F.SH), (0, 0, 0, 0))
            o = imgs[p + "_o"]
            full.paste(imgs[p], (o[0], o[1]), imgs[p])
            im = full.resize((cw, ch), Image.LANCZOS)
            bg = Image.new("RGB", (cw, ch), (58, 46, 66))
            bg.paste(im, (0, 0), im)
            sheet.paste(bg, (c * cw, r * (ch + 20) + 20))
            d.text((c * cw + 4, r * (ch + 20) + 4),
                   "%s %s" % (F.CHARS[ci]["short"], p), fill=(255, 255, 120))
    sheet.save("fight_frames.png")
    print("fight_frames.png", sheet.size)


def scene():
    """把两个角色摆到背景上, 看整体效果"""
    bg = F.make_bg().copy()
    f1 = F.Fighter(0, F.build_frames(0), 340, 1, "火影")
    f2 = F.Fighter(1, F.build_frames(1), 690, -1, "死神")
    d = ImageDraw.Draw(bg)
    for ftr in (f1, f2):
        im = ftr.frames["idle"]
        if ftr.face < 0:
            im = ftr.frames["idle_m"]
        cx, by = int(ftr.x), int(F.GROUND_Y)
        sw = 42
        d.ellipse([cx - sw, F.GROUND_Y - 8, cx + sw, F.GROUND_Y + 10],
                  fill=(40, 28, 24))
        bg.paste(im, (cx - F.FOOT[0], by - F.FOOT[1]), im)
    # 攻击姿态对比图
    im2 = bg.copy()
    ia = F.build_frames(1)["atk_h"]
    im2.paste(ia, (690 - F.FOOT[0], F.GROUND_Y - F.FOOT[1]), ia)
    out = Image.new("RGB", (F.W, F.H * 2 + 10), (20, 20, 24))
    out.paste(bg, (0, 0))
    out.paste(im2, (0, F.H + 10))
    out.save("fight_scene.png")
    print("fight_scene.png", out.size)


def hud_preview():
    """用假屏幕跑一遍 Fight, 把 HUD + 角色 + 按钮整幅画出来"""
    import fbui

    class FakeScreen(fbui.Screen):
        def __init__(self):
            self.w, self.h, self.vh = F.W, F.H, 1200
            self.bpp, self.bppx, self.stride = 24, 3, F.W * 3
            self.phys = 0
            self.gpu = None
            self.mode = "BGR;24"
            self._fast = True
            self.img = Image.new("RGB", (F.W, F.H), (12, 16, 32))
            self.d = ImageDraw.Draw(self.img)
            self.frames = 0

        def flush(self, box=None):
            self.frames += 1

        def to_raw(self, im):
            return im.convert(self.mode).tobytes()

        def blit_raw(self, x0, y0, w, h, data):
            pass

    class T:
        down = False
        x = y = 0

        def poll(self, move=False):
            return None

    scr = FakeScreen()
    g = F.Fight(scr, T())
    g.state = "fight"
    g.timer = 43.0
    g.wins = [1, 0]
    g.f1.hp = 78
    g.hp_lag = [92.0, 100.0]
    g.f2.hp = 100
    g.f1.mp = 60
    g.f2.mp = 100
    g.f1.combo_hit = 3
    g.f2.x = 690
    g.draw({})
    scr.img.save("fight_hud.png")
    print("fight_hud.png", scr.img.size)


hud_preview()
frames_sheet()
scene()
