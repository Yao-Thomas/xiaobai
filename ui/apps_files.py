#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_files.py —— 文件管理器 (浏览 / 看图片 / 看文本)"""
import os, time
from fbui import header, back_hit, btn, hit

WANT_DIRS = ["/home/zynq", "/home/zynq/Pictures", "/home/zynq/ui", "/lib/firmware", "/", "/tmp"]
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
TXT_EXT = (".txt", ".md", ".py", ".sh", ".c", ".h", ".conf", ".log", ".list")


def human(n):
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return "%d%s" % (n, u)
        n /= 1024.0
    return "%.1fT" % n


def folders():
    """只列出真实存在且可读的目录"""
    return [d for d in WANT_DIRS if os.path.isdir(d) and os.access(d, os.R_OK)]


def listing(path):
    items = []
    try:
        for name in sorted(os.listdir(path)):
            if name.startswith("."):
                continue
            fp = os.path.join(path, name)
            try:
                isdir = os.path.isdir(fp)
                sz = 0 if isdir else os.path.getsize(fp)
            except OSError:
                continue
            items.append((name, fp, isdir, sz))
    except Exception:
        pass
    items.sort(key=lambda t: (not t[2], t[0].lower()))
    return items


def draw(scr, path, items, msg=""):
    scr.clear((16, 22, 40))
    header(scr, "文件管理器")
    scr.rrect([52, 70, scr.w - 52, 112], 8, fill=(24, 32, 56))
    scr.text((66, 91), path, 20, (150, 200, 255), anchor="lm", mono=True)
    x = 52
    for d in folders():
        nm = os.path.basename(d) or "/"
        w = scr.tw(nm, 16) + 28
        btn(scr, [x, 120, x + w, 156], nm, fill=(44, 58, 92), size=16)
        x += w + 8
    y = 168
    for i, (name, fp, isdir, sz) in enumerate(items[:9]):
        r = [52, y, scr.w - 52, y + 44]
        scr.rrect(r, 8, fill=(40, 54, 88) if i % 2 == 0 else (34, 46, 76))
        if isdir:
            ic = (250, 200, 80)
            scr.d.rectangle([66, y + 14, 84, y + 32], fill=ic)
            scr.d.rectangle([68, y + 10, 80, y + 16], fill=ic)
        elif name.lower().endswith(IMG_EXT):
            scr.d.rectangle([66, y + 13, 84, y + 31], fill=(90, 200, 150))
            scr.d.ellipse([69, y + 16, 75, y + 22], fill=(255, 255, 255))
        else:
            scr.d.rectangle([66, y + 12, 84, y + 32], fill=(150, 170, 210))
        scr.text((96, y + 22), name[:52], 20, (235, 242, 255), anchor="lm", cn=True)
        if not isdir:
            scr.text((scr.w - 66, y + 22), human(sz), 17, (140, 160, 200), anchor="rm")
        y += 48
    if not items:
        scr.text((512, 300), "（空目录或无权限）", 24, (160, 170, 200), cn=True, anchor="mm")
    if msg:
        scr.text((512, scr.h - 12), msg, 17, (140, 220, 180), cn=True, anchor="mb")


def view_image(scr, touch, path):
    from PIL import Image
    try:
        im = Image.open(path).convert("RGB")
    except Exception as ex:
        return "打不开: %s" % ex
    im.thumbnail((900, 440))
    while True:
        scr.clear((10, 12, 22))
        header(scr, os.path.basename(path)[:40])
        scr.img.paste(im, ((scr.w - im.width) // 2, 74 + (440 - im.height) // 2))
        scr.text((512, scr.h - 16), "%s   %dx%d   (点屏幕返回)" %
                 (os.path.basename(path)[:30], im.width, im.height), 17,
                 (150, 170, 210), anchor="mb")
        scr.flush()
        if touch.poll():
            return ""


def view_text(scr, touch, path):
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as ex:
        return "读不了: %s" % ex
    top = 0
    while True:
        scr.clear((14, 18, 32))
        header(scr, os.path.basename(path)[:40])
        y = 74
        for ln in lines[top:top + 17]:
            scr.text((60, y), ln[:78], 19, (215, 225, 245), mono=True)
            y += 28
        scr.text((512, scr.h - 14), "第 %d/%d 行   点上/下半屏翻页, 返回键退出" %
                 (top + 1, max(1, len(lines))), 16, (140, 160, 200), cn=True, anchor="mb")
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return ""
            top = max(0, top - 15) if y < scr.h // 2 else min(max(0, len(lines) - 17), top + 15)


def run(scr, touch):
    path = "/home/zynq"
    msg = ""
    while True:
        items = listing(path)
        draw(scr, path, items, msg)
        scr.flush()
        msg = ""
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            x2 = 52
            jumped = False
            for d in folders():
                nm = os.path.basename(d) or "/"
                w = scr.tw(nm, 16) + 28
                if hit([x2, 120, x2 + w, 156], x, y):
                    path = d
                    jumped = True
                    break
                x2 += w + 8
            if jumped:
                continue
            if 168 <= y < 168 + 9 * 48 and 52 <= x <= scr.w - 52:
                idx = (y - 168) // 48
                if idx < len(items):
                    name, fp, isdir, sz = items[idx]
                    if isdir:
                        path = fp
                    elif name.lower().endswith(IMG_EXT):
                        msg = view_image(scr, touch, fp) or "查看完成"
                    elif name.lower().endswith(TXT_EXT):
                        msg = view_text(scr, touch, fp) or "查看完成"
                    else:
                        msg = "不支持的类型: " + name[:30]
        time.sleep(0.03)
