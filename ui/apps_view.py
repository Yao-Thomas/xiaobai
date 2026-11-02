#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_view.py —— 图片查看器 (支持删除)"""
import os, time
from fbui import header, back_hit, btn, hit

DIRS = ["/home/zynq/Pictures", "/home/zynq", "/tmp", "/usr/share/plymouth"]
EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

PER_PAGE = 8
DEL_W = 62          # 每行右侧的删除按钮宽度


def scan():
    """扫描所有图片"""
    out = []
    for d in DIRS:
        if not os.path.isdir(d):
            continue
        try:
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(EXTS):
                    out.append(os.path.join(d, n))
        except Exception:
            pass
    return out


def row_rect(scr, i):
    y = 74 + i * 56
    return [52, y, scr.w - 52, y + 50]


def del_rect(scr, i):
    """第 i 行的删除按钮"""
    r = row_rect(scr, i)
    return [r[2] - DEL_W - 10, r[1] + 9, r[2] - 10, r[3] - 9]


def confirm_del(scr, touch, name):
    """删除确认框. 返回 True=确认删除"""
    box = [262, 236, 762, 386]
    okr = [300, 316, 480, 370]      # 删除
    ccr = [544, 316, 724, 370]      # 取消
    while True:
        # 半透明遮罩 + 对话框
        scr.rrect(box, 14, fill=(28, 34, 52), outline=(120, 70, 70))
        scr.text((512, 276), "删除这张图片?", 26, (255, 220, 220), cn=True, anchor="mm")
        nm = name if len(name) <= 34 else name[:31] + "..."
        scr.text((512, 306), nm, 17, (180, 195, 225), cn=True, anchor="mm")
        btn(scr, okr, "删除", fill=(190, 60, 60), size=20, cn=True)
        btn(scr, ccr, "取消", fill=(60, 76, 110), size=20, cn=True)
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if hit(okr, x, y):
                return True
            if hit(ccr, x, y) or back_hit(x, y):
                return False
        time.sleep(0.03)


def do_delete(scr, touch, path):
    """执行删除, 返回提示文字"""
    from apps_view import confirm_del as _c     # 保持一致性
    if not confirm_del(scr, touch, os.path.basename(path)):
        return "已取消"
    try:
        os.remove(path)
        print("图片已删除:", path)
        return "已删除: " + os.path.basename(path)
    except Exception as ex:
        return "删除失败: %s" % ex


def list_view(scr, files, page, msg="", selected=None):
    scr.clear((14, 18, 32))
    header(scr, "图片查看器")
    total_pages = max(1, (len(files) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    for i, f in enumerate(files[page * PER_PAGE:(page + 1) * PER_PAGE]):
        r = row_rect(scr, i)
        bg = (46, 62, 100) if i % 2 == 0 else (36, 50, 80)
        scr.rrect(r, 8, fill=bg)
        scr.d.rectangle([68, r[1] + 14, 90, r[1] + 36], fill=(90, 200, 150))
        scr.d.ellipse([72, r[1] + 18, 80, r[1] + 26], fill=(255, 255, 255))

        dr = del_rect(scr, i)
        # 名称(给删除按钮留位置)
        scr.text((104, r[1] + 25), os.path.basename(f)[:40], 19, (232, 242, 255),
                 cn=True, anchor="lm")
        # 大小
        try:
            scr.text((dr[0] - 14, r[1] + 25), "%.0f KB" % (os.path.getsize(f) / 1024.0),
                     16, (140, 165, 205), anchor="rm")
        except Exception:
            pass
        # 删除按钮
        btn(scr, dr, "删", fill=(150, 55, 55), size=19, cn=True,
            outline=(200, 90, 90))

    if not files:
        scr.text((512, 300), "没有找到图片\n(用画板画几张试试)", 26, (170, 185, 215),
                 cn=True, anchor="mm")

    # 翻页
    if total_pages > 1:
        btn(scr, [52, scr.h - 56, 200, scr.h - 14], "< 上一页", fill=(50, 66, 100),
            size=18, cn=True)
        btn(scr, [scr.w - 200, scr.h - 56, scr.w - 52, scr.h - 14], "下一页 >",
            fill=(50, 66, 100), size=18, cn=True)
        scr.text((512, scr.h - 35), "第 %d / %d 页" % (page + 1, total_pages), 17,
                 (150, 175, 215), cn=True, anchor="mm")
    else:
        scr.text((512, scr.h - 35), "共 %d 张  ·  点行选中, 点红色\"删\"删除"
                 % len(files), 17, (130, 155, 195), cn=True, anchor="mm")
    if msg:
        scr.text((512, scr.h - 70), msg, 17, (140, 220, 180), cn=True, anchor="mm")
    return page, total_pages


def show_image(scr, touch, path):
    """全屏查看. 返回 (提示文字, 是否已删除)"""
    from PIL import Image
    try:
        im = Image.open(path).convert("RGB")
    except Exception as ex:
        return "打不开: %s" % ex, False
    orig = im.size
    im.thumbnail((900, 400))
    fit = True
    while True:
        scr.clear((8, 10, 18))
        header(scr, os.path.basename(path)[:40])
        if fit:
            pic = im
        else:
            pic = Image.open(path).convert("RGB")
            pic.thumbnail((1010, 470))
        scr.img.paste(pic, ((scr.w - pic.width) // 2, 64 + (480 - pic.height) // 2))
        b1 = [52, scr.h - 54, 190, scr.h - 12]
        b2 = [204, scr.h - 54, 342, scr.h - 12]
        b3 = [356, scr.h - 54, 494, scr.h - 12]
        b4 = [scr.w - 190, scr.h - 54, scr.w - 52, scr.h - 12]
        btn(scr, b1, "适应" if not fit else "原始", fill=(52, 84, 140), size=18, cn=True)
        btn(scr, b2, "关闭", fill=(90, 70, 60), size=18, cn=True)
        btn(scr, b3, "返回列表", fill=(46, 110, 90), size=18, cn=True)
        btn(scr, b4, "删除图片", fill=(170, 55, 55), size=18, cn=True)
        scr.text((510, scr.h - 33), "%dx%d   %s" % (orig[0], orig[1],
                 os.path.basename(path)[:24]), 16, (150, 175, 215), anchor="lm")
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y) or hit(b2, x, y) or hit(b3, x, y):
                return "", False
            if hit(b1, x, y):
                fit = not fit
            if hit(b4, x, y):
                msg = do_delete(scr, touch, path)
                if msg.startswith("已删除"):
                    return msg, True
                return msg, False


def run(scr, touch):
    files = scan()
    page = 0
    msg = ""
    while True:
        page, total = list_view(scr, files, page, msg)
        scr.flush()
        msg = ""
        ev = touch.poll()
        if ev:
            _, x, y = ev
            print("图片查看器: 点击 (%d,%d)" % (x, y))
            if back_hit(x, y):
                return
            if total > 1 and hit([52, scr.h - 56, 200, scr.h - 14], x, y):
                page = max(0, page - 1)
                continue
            if total > 1 and hit([scr.w - 200, scr.h - 56, scr.w - 52, scr.h - 14], x, y):
                page = min(total - 1, page + 1)
                continue
            # 每行的删除按钮
            hit_del = False
            for i in range(PER_PAGE):
                idx = page * PER_PAGE + i
                if idx >= len(files):
                    break
                if hit(del_rect(scr, i), x, y):
                    print("  -> 命中删除按钮 行%d: %s" %
                          (i, os.path.basename(files[idx])))
                    msg = do_delete(scr, touch, files[idx])
                    if msg.startswith("已删除"):
                        files = scan()                  # 重新扫描
                        total_pages = max(1, (len(files) + PER_PAGE - 1) // PER_PAGE)
                        page = min(page, total_pages - 1)
                    hit_del = True
                    break
            if hit_del:
                continue
            # 点行 -> 全屏查看
            if 74 <= y < 74 + PER_PAGE * 56 and 52 <= x <= scr.w - 52:
                idx = page * PER_PAGE + (y - 74) // 56
                if 0 <= idx < len(files):
                    m, deleted = show_image(scr, touch, files[idx])
                    if deleted:
                        files = scan()
                        total_pages = max(1, (len(files) + PER_PAGE - 1) // PER_PAGE)
                        page = min(page, total_pages - 1)
                    msg = m or "已关闭"
        time.sleep(0.03)
