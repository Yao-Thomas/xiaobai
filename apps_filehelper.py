#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_filehelper.py —— 文件传输助手（板子端）

════════════════════════════════════════════════════════════════════
为什么单独做一个 App（而不是塞进 apps_files.py）
════════════════════════════════════════════════════════════════════
用户原话："还有文件同步传输，就是加一个文件传输助手软件在板子里"

apps_files.py 是【通用文件管理器】—— 浏览、看图片、看文本。
这个「助手」只干一件事：**把 PC 传过来的东西收好、看清楚**。

区别体现在：
    · 只看一个目录（接收区 /home/zynq/received），不迷路
    · 大字显示"收到什么、多大、什么时候"
    · ★ 顶部直接显示板子的 IP + 端口 + token —— PC 端要连的时候照着填
    · 一键清空 / 删单个
    · 图片直接预览（不用先进文件管理器翻）

════════════════════════════════════════════════════════════════════
PC 端怎么把文件送进来
════════════════════════════════════════════════════════════════════
走板子早就有的接口（cloud_api.py）：
    POST /fs/upload/begin   {path, size, md5}   -> {upload_id}
    POST /fs/upload/chunk   {upload_id, offset, data(base64)}
    POST /fs/upload/end     {upload_id}         -> 校验 md5
PC 客户端的「📁 文件」页勾「传到接收区」就会落到这个目录。

★ 为什么要单独一个"接收区"：
  默认上传是落到 PC 端当前浏览的目录，可能被传到 /lib/firmware 之类
  让人找不着的地方。接收区固定，板子上打开这个 App 就一定能看到。
════════════════════════════════════════════════════════════════════
"""
import os
import time

from fbui import header, back_hit, btn, hit

# ★ 接收区：PC 端"传到接收区"就落这里
RECV_DIR = os.environ.get("XIAOBAI_RECV", "/home/zynq/received")

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
TXT_EXT = (".txt", ".md", ".py", ".sh", ".c", ".h", ".conf", ".log",
           ".json", ".csv")


def human(n):
    try:
        n = float(n)
    except Exception:
        return "—"
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return "%dB" % int(n) if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0
    return "%.1fT" % n


def ensure_dir():
    """接收区不存在就建（PC 端第一次传之前也得有）"""
    try:
        os.makedirs(RECV_DIR, exist_ok=True)
        return True
    except Exception:
        return False


def listing():
    """列接收区的文件（新的在前）"""
    ensure_dir()
    out = []
    try:
        for name in os.listdir(RECV_DIR):
            if name.startswith("."):
                continue
            fp = os.path.join(RECV_DIR, name)
            try:
                st = os.stat(fp)
                out.append({
                    "name": name, "path": fp,
                    "dir": os.path.isdir(fp),
                    "size": 0 if os.path.isdir(fp) else st.st_size,
                    "mtime": st.st_mtime,
                })
            except OSError:
                continue
    except Exception:
        pass
    out.sort(key=lambda x: -x["mtime"])
    return out


def board_addr():
    """板子的 IP（给 PC 端照着填）"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


def board_token():
    """从 cloud-api 的配置里读 token（PC 端要填）"""
    try:
        import json
        with open("/etc/xiaobai-cloud.json", encoding="utf-8") as f:
            return (json.load(f) or {}).get("token") or "?"
    except Exception:
        return "?"


def ago(ts):
    """多久以前"""
    try:
        d = int(time.time() - float(ts))
    except Exception:
        return "?"
    if d < 60:
        return "%d 秒前" % d
    if d < 3600:
        return "%d 分钟前" % (d // 60)
    if d < 86400:
        return "%d 小时前" % (d // 3600)
    return "%d 天前" % (d // 86400)


def view_image(scr, touch, path):
    """全屏看图片（点一下返回）"""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
    except Exception as ex:
        return "打不开: %s" % ex
    im.thumbnail((940, 430))
    while True:
        scr.clear((12, 12, 12))
        header(scr, os.path.basename(path)[:40])
        scr.img.paste(im, ((scr.w - im.width) // 2,
                           74 + (430 - im.height) // 2))
        scr.text((512, scr.h - 16),
                 "%s   %dx%d   (点屏幕返回)" % (os.path.basename(path)[:30],
                                               im.width, im.height),
                 17, (150, 170, 210), anchor="mb")
        scr.flush()
        if touch.poll():
            return ""


def view_text(scr, touch, path):
    """翻页看文本"""
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as ex:
        return "读不了: %s" % ex
    top = 0
    while True:
        scr.clear((18, 18, 18))
        header(scr, os.path.basename(path)[:40])
        y = 74
        for ln in lines[top:top + 16]:
            scr.text((56, y), ln[:76], 19, (224, 224, 224), mono=True)
            y += 30
        scr.text((512, scr.h - 14),
                 "第 %d/%d 行   点上/下半屏翻页，返回键退出"
                 % (top + 1, max(1, len(lines))),
                 16, (140, 160, 200), cn=True, anchor="mb")
        scr.flush()
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return ""
            top = (max(0, top - 15) if y < scr.h // 2
                   else min(max(0, len(lines) - 16), top + 15))


def draw(scr, items, sel, msg=""):
    """画主界面"""
    scr.clear((20, 22, 26))
    header(scr, "文件传输助手")

    # ── 顶部：连接信息（PC 端照着填）──
    scr.rrect([40, 66, scr.w - 40, 148], 10, fill=(30, 38, 52))
    scr.text((56, 86), "PC 端连接信息", 16, (140, 180, 240), cn=True)
    scr.text((56, 112), "IP %s    端口 8768    token %s"
             % (board_addr(), board_token()),
             21, (235, 240, 250), mono=True)
    scr.text((56, 138), "接收区：%s" % RECV_DIR, 15, (150, 165, 190),
             mono=True)

    # ── 统计 ──
    nfile = sum(1 for x in items if not x["dir"])
    nbyte = sum(x["size"] for x in items if not x["dir"])
    scr.text((scr.w - 56, 86), "共 %d 个文件，%s" % (nfile, human(nbyte)),
             17, (160, 200, 170), cn=True, anchor="rm")
    scr.text((scr.w - 56, 112), "（刚收到的排在最上面）", 14,
             (130, 145, 170), cn=True, anchor="rm")

    # ── 文件列表 ──
    y = 160
    n_show = 7
    if not items:
        scr.text((512, 300), "接收区还是空的", 26, (150, 165, 195),
                 cn=True, anchor="mm")
        scr.text((512, 336), "PC 客户端 →「📁 文件」页 →「传到接收区」",
                 18, (120, 135, 165), cn=True, anchor="mm")
    for i, it in enumerate(items[:n_show]):
        r = [40, y, scr.w - 40, y + 50]
        on = (i == sel)
        scr.rrect(r, 9, fill=(46, 68, 110) if on else (34, 42, 56))
        name = it["name"]
        # 图标
        if it["dir"]:
            scr.d.rectangle([56, y + 16, 76, y + 38], fill=(250, 200, 80))
            scr.d.rectangle([58, y + 11, 72, y + 19], fill=(250, 200, 80))
        elif name.lower().endswith(IMG_EXT):
            scr.d.rectangle([56, y + 15, 76, y + 37], fill=(90, 200, 150))
            scr.d.ellipse([59, y + 19, 66, y + 26], fill=(255, 255, 255))
        elif name.lower().endswith(TXT_EXT):
            scr.d.rectangle([56, y + 14, 76, y + 38], fill=(150, 170, 210))
        else:
            scr.d.rectangle([56, y + 14, 76, y + 38], fill=(120, 140, 180))
        scr.text((90, y + 25), name[:44], 21, (240, 242, 246), anchor="lm",
                 cn=True)
        scr.text((scr.w - 60, y + 15), human(it["size"]) if not it["dir"]
                 else "目录", 18, (160, 180, 215), anchor="rm")
        scr.text((scr.w - 60, y + 36), ago(it["mtime"]), 15,
                 (130, 150, 180), cn=True, anchor="rm")
        y += 56

    # ── 底部按钮 ──
    by = scr.h - 60
    btn(scr, [40, by, 190, by + 44], "刷新", fill=(44, 58, 92), size=19,
        cn=True)
    btn(scr, [200, by, 360, by + 44], "打开选中", fill=(40, 74, 70),
        size=19, cn=True)
    btn(scr, [370, by, 520, by + 44], "删除选中", fill=(92, 46, 46),
        size=19, cn=True)
    btn(scr, [530, by, 690, by + 44], "清空接收区", fill=(92, 60, 40),
        size=19, cn=True)
    btn(scr, [700, by, scr.w - 40, by + 44], "打开文件管理器",
        fill=(48, 48, 66), size=19, cn=True)

    if msg:
        scr.text((512, by - 14), msg, 17, (150, 220, 180), cn=True,
                 anchor="mb")


def run(scr, touch):
    """App 入口（和别的 app 一样的约定）"""
    ensure_dir()
    sel = 0
    msg = ""
    while True:
        items = listing()
        if sel >= len(items):
            sel = max(0, len(items) - 1)
        draw(scr, items, sel, msg)
        scr.flush()
        msg = ""

        ev = touch.poll()
        if not ev:
            time.sleep(0.05)
            continue
        _, x, y = ev
        if back_hit(x, y):
            return

        # 文件行：点一下选中，再点一下打开
        if 160 <= y < 160 + 7 * 56 and 40 <= x <= scr.w - 40:
            idx = (y - 160) // 56
            if idx < len(items):
                if idx == sel:
                    # ★ 再点一次 = 打开
                    it = items[idx]
                    if it["dir"]:
                        msg = "这是目录（用文件管理器进）"
                    elif it["name"].lower().endswith(IMG_EXT):
                        msg = view_image(scr, touch, it["path"]) or "看完了"
                    elif it["name"].lower().endswith(TXT_EXT):
                        msg = view_text(scr, touch, it["path"]) or "看完了"
                    else:
                        msg = "这个类型看不了（可以下载到 PC 看）"
                else:
                    sel = idx
                continue

        by = scr.h - 60
        if not (by <= y <= by + 44):
            time.sleep(0.03)
            continue

        # ── 底部按钮 ──
        if hit([40, by, 190, by + 44], x, y):
            msg = "已刷新（%d 项）" % len(items)
        elif hit([200, by, 360, by + 44], x, y):
            if not items:
                msg = "接收区是空的"
            else:
                it = items[sel]
                if it["dir"]:
                    msg = "目录（用文件管理器进）"
                elif it["name"].lower().endswith(IMG_EXT):
                    msg = view_image(scr, touch, it["path"]) or "看完了"
                elif it["name"].lower().endswith(TXT_EXT):
                    msg = view_text(scr, touch, it["path"]) or "看完了"
                else:
                    msg = "这个类型看不了"
        elif hit([370, by, 520, by + 44], x, y):
            if items:
                it = items[sel]
                try:
                    if it["dir"]:
                        os.rmdir(it["path"])
                    else:
                        os.remove(it["path"])
                    msg = "已删除：%s" % it["name"][:24]
                except Exception as ex:
                    msg = "删不掉：%s" % ex
        elif hit([530, by, 690, by + 44], x, y):
            n = 0
            for it in items:
                try:
                    if it["dir"]:
                        os.rmdir(it["path"])
                    else:
                        os.remove(it["path"])
                    n += 1
                except Exception:
                    pass
            msg = "已清空 %d 项" % n
        elif hit([700, by, scr.w - 40, by + 44], x, y):
            # 交给桌面去开文件管理器（这里只是提示）
            msg = "返回桌面 →「文件管理器」可以浏览全部目录"
        time.sleep(0.03)
