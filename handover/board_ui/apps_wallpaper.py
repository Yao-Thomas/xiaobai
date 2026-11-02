#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_wallpaper.py —— 壁纸软件

功能:
  - 自动收集 /home/zynq/Pictures/ 和它的 wallpapers/ 子目录里的图片
  - 缩略图网格展示, 当前壁纸有高亮边框
  - 点一下就切换壁纸 (立刻生效, 并记到 ~/.wallpaper)
  - 「恢复默认壁纸」按钮
  - 支持 "适合屏幕 / 填充裁剪" 两种缩放方式 (点击缩略图切换时用填充)
"""
import os, glob

PICDIR = "/home/zynq/Pictures"
WALLDIR = os.path.join(PICDIR, "wallpapers")
CONF = "/home/zynq/.wallpaper"
DEFAULT_WALL = os.path.join(WALLDIR, "默认壁纸.png")
EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

THUMB_W, THUMB_H = 150, 88          # 4:3 不到, 接近 16:9
THUMB_CACHE = "/home/zynq/.cache/wall_thumbs"   # 缩略图缓存 (持久化, 重启不丢)


def list_wallpapers():
    """收集所有可用作壁纸的图片, 默认壁纸排第一位"""
    files = []
    for d in (WALLDIR, PICDIR):
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "*"))):
            if f.lower().endswith(EXTS) and os.path.isfile(f) and f not in files:
                # 只收第一层, wallpapers 里的已单独收过
                if os.path.dirname(f) == WALLDIR or d == PICDIR:
                    files.append(f)
    # 默认壁纸放最前
    if DEFAULT_WALL in files:
        files.remove(DEFAULT_WALL)
        files.insert(0, DEFAULT_WALL)
    return files


def current_wall():
    try:
        with open(CONF) as f:
            p = f.read().strip()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    return DEFAULT_WALL


def set_wall(path):
    try:
        with open(CONF, "w") as f:
            f.write(path + "\n")
        return True
    except Exception:
        return False


def _cache_path(path):
    """缩略图缓存文件路径 (按 文件路径+修改时间+大小 做键)"""
    try:
        st = os.stat(path)
        key = "%s|%d|%d" % (path, int(st.st_mtime), st.st_size)
    except Exception:
        key = path
    import hashlib
    h = hashlib.md5(key.encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.join(THUMB_CACHE, h + ".png")


def make_thumb(path):
    """取缩略图 (优先用磁盘缓存, 没有才现做)"""
    from PIL import Image
    cp = _cache_path(path)
    if os.path.isfile(cp):
        try:
            return Image.open(cp).convert("RGB")
        except Exception:
            pass
    im = Image.open(path).convert("RGB")
    tw, th = THUMB_W, THUMB_H
    iw, ih = im.size
    sc = max(tw / float(iw), th / float(ih))
    im = im.resize((max(1, int(iw * sc)), max(1, int(ih * sc))), Image.BILINEAR)
    iw, ih = im.size
    l = (iw - tw) // 2
    t = (ih - th) // 2
    im = im.crop((l, t, l + tw, t + th))
    # 存缓存 (失败也不影响使用)
    try:
        os.makedirs(THUMB_CACHE, exist_ok=True)
        im.save(cp)
    except Exception:
        pass
    return im


def warm_cache(files=None):
    """预生成所有缩略图 (可以在后台先跑一遍, 打开应用就秒开)"""
    files = files if files is not None else list_wallpapers()
    n = 0
    for f in files:
        try:
            make_thumb(f)
            n += 1
        except Exception:
            pass
    return n


def draw(scr, files, cur, sel, msg, page):
    from fbui import header, back_hit
    scr.clear((17, 17, 17))
    header(scr, "壁纸")

    # 状态行
    scr.rrect([20, 72, scr.w - 20, 116], 10, fill=(39, 39, 39))
    name = os.path.basename(cur) if cur else "内置渐变"
    scr.text((40, 94), "当前: " + name, 20, (170, 230, 255), cn=True, anchor="lm")
    if msg:
        scr.text((scr.w - 40, 94), msg[:30], 18, (250, 210, 140), cn=True, anchor="rm")

    # 按钮行
    y = 124
    scr.rrect([20, y, 240, y + 46], 10, fill=(40, 120, 190))
    scr.text((130, y + 23), "重新扫描", 20, (255, 255, 255), cn=True, anchor="mm")
    scr.rrect([256, y, 476, y + 46], 10, fill=(120, 90, 40))
    scr.text((366, y + 23), "恢复默认壁纸", 20, (255, 255, 255), cn=True, anchor="mm")
    scr.text((500, y + 23), "共 %d 张   图片放 /home/zynq/Pictures/" % len(files),
             17, (150, 190, 220), cn=True, anchor="lm")

    # 网格
    cols = 5
    gx, gy = 20, 184
    step_x, step_y = THUMB_W + 18, THUMB_H + 34
    per_page = cols * 3                      # 每页 15 张
    total_page = max(1, (len(files) + per_page - 1) // per_page)
    page = max(0, min(page, total_page - 1))

    for i, f in enumerate(files[page * per_page:(page + 1) * per_page]):
        r, c = i // cols, i % cols
        x = gx + c * step_x
        yy = gy + r * step_y
        is_cur = (os.path.abspath(f) == os.path.abspath(cur))
        is_sel = (f == sel)
        try:
            thumb = make_thumb(f)
            scr.d.rectangle([x, yy, x + THUMB_W, yy + THUMB_H], fill=(28, 28, 28))
            scr.img.paste(thumb, (x, yy))
        except Exception:
            scr.rrect([x, yy, x + THUMB_W, yy + THUMB_H], 6, fill=(60, 30, 30))
        # 边框: 当前=绿, 选中=蓝, 其它=灰
        if is_cur:
            scr.rect([x - 3, yy - 3, x + THUMB_W + 3, yy + THUMB_H + 3],
                     outline=(90, 230, 140), width=3)
        elif is_sel:
            scr.rect([x - 3, yy - 3, x + THUMB_W + 3, yy + THUMB_H + 3],
                     outline=(90, 170, 255), width=3)
        else:
            scr.rect([x - 1, yy - 1, x + THUMB_W + 1, yy + THUMB_H + 1],
                     outline=(50, 70, 95), width=1)
        label = os.path.basename(f)
        if len(label) > 12:
            label = label[:11] + "…"
        scr.text((x + THUMB_W // 2, yy + THUMB_H + 14), label, 15,
                 (150, 230, 170) if is_cur else (212, 212, 212),
                 cn=True, anchor="mm")

    # 翻页提示
    if total_page > 1:
        scr.text((scr.w // 2, scr.h - 60), "第 %d / %d 页  (左右点屏幕边缘翻页)"
                 % (page + 1, total_page), 18, (140, 180, 210), cn=True, anchor="mm")
    scr.text((scr.w // 2, scr.h - 30), "点缩略图即刻切换壁纸", 18,
             (120, 160, 190), cn=True, anchor="mm")
    return page, per_page, cols, gx, gy, step_x, step_y, total_page


def run(scr, touch):
    import subprocess, time

    # ★ 关键: 先把触摸队列清空, 并忽略前 0.5 秒的点击
    #   否则"点图标启动应用"的那一下会被应用当成第一次点击
    try:
        for _ in range(20):
            if touch.poll() is None:
                break
            time.sleep(0.01)
    except Exception:
        pass
    t_start = time.time()

    files = list_wallpapers()
    cur = current_wall()
    sel = None
    msg = ""
    page = 0
    dirty = True
    geom = None
    print("壁纸应用: 打开, 共 %d 张图, 当前=%s" %
          (len(files), os.path.basename(cur)), flush=True)

    while True:
        if dirty:
            geom = draw(scr, files, cur, sel, msg, page)
            scr.flush()
            dirty = False
            page, per_page, cols, gx, gy, sx, sy, total_page = geom

        ev = touch.poll()
        if ev:
            kind, x, y = ev
            print("壁纸应用: 点击 (%d,%d)" % (x, y), flush=True)
            # 启动后 0.5 秒内的点击一律忽略 (防穿透)
            if time.time() - t_start < 0.5:
                print("壁纸应用: (启动瞬间, 忽略)", flush=True)
                continue
            # 返回
            if 10 <= x <= 130 and 8 <= y <= 52:
                print("壁纸应用: 返回桌面", flush=True)
                return
            # 按钮
            if 124 <= y <= 170:
                if 20 <= x <= 240:
                    # 重新扫描 (上传了新图片就用这个刷新)
                    files = list_wallpapers()
                    cur = current_wall()
                    page = 0
                    msg = "重新扫描: %d 张图片" % len(files)
                    dirty = True
                    continue
                if 256 <= x <= 476:
                    if set_wall(DEFAULT_WALL):
                        cur = DEFAULT_WALL
                        msg = "已恢复默认壁纸"
                    else:
                        msg = "设置失败"
                    dirty = True
                    continue

            # 翻页 (点屏幕左右边缘)
            if geom and total_page > 1:
                if x < 14 and y > 180:
                    page = max(0, page - 1)
                    dirty = True
                    continue
                if x > scr.w - 14 and y > 180:
                    page = min(total_page - 1, page + 1)
                    dirty = True
                    continue

            # 缩略图点击
            if geom:
                page, per_page, cols, gx, gy, sx, sy, total_page = geom
                idx_in_page = -1
                for i in range(per_page):
                    r, c = i // cols, i % cols
                    x0 = gx + c * sx
                    y0 = gy + r * sy
                    if x0 <= x <= x0 + THUMB_W and y0 <= y <= y0 + THUMB_H:
                        idx_in_page = i
                        break
                if idx_in_page >= 0:
                    gi = page * per_page + idx_in_page
                    print("壁纸应用: 缩略图 第%d页 第%d格 -> 全局%d" %
                          (page, idx_in_page, gi), flush=True)
                    if 0 <= gi < len(files):
                        f = files[gi]
                        sel = f
                        if set_wall(f):
                            cur = f
                            msg = "已设为壁纸: " + os.path.basename(f)[:14]
                            print("壁纸应用: ★ 已设为 %s" % f, flush=True)
                        else:
                            msg = "写入失败"
                        dirty = True
                        continue

        import time
        time.sleep(0.05)
