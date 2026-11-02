#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desktop.py v2 —— Zynq 板载自研桌面 (美化版)
  · 渐变壁纸 + 光晕 + 网格 + 水印
  · 图标居中网格布局
  · 按下高亮反馈
  · 开始菜单(下拉应用列表)
  · 状态栏: CPU / 内存 / 时钟
用法: sudo python3 desktop.py
"""
import os, sys, time, datetime, math
sys.path.insert(0, "/home/zynq/ui")
from fbui import Screen, Touch, font, hit
import fbui
from PIL import Image, ImageDraw, ImageFilter

# ============ 配色 ============
C_TOP      = (30, 44, 86)
C_BOT      = (7, 9, 20)
C_TASKBAR1 = (22, 30, 54)
C_TASKBAR2 = (14, 19, 36)
C_LINE     = (56, 84, 140)
C_ICON_BG  = (44, 66, 118)
C_ICON_BG2 = (62, 92, 156)
C_ICON_PR  = (120, 170, 255)
C_TEXT     = (238, 243, 255)
C_TEXT_DIM = (148, 166, 200)
C_ACCENT   = (86, 166, 255)
C_MENU_BG  = (20, 27, 48)
C_MENU_HD  = (44, 62, 108)

TB_H = 56
ICON_W, ICON_H = 96, 96
GAP_X, GAP_Y = 34, 44
ICON_TOP = 104
DRAG_HOLD = 0.30      # 按住多久算"长按"(秒)
DRAG_MOVE = 12        # 手指至少移动多少像素才算拖动(否则还是点击)
SWIPE_MIN = 220       # 翻页需要的最小横向位移(像素) —— 太小会误触
EDGE_ZONE = 90        # 拖动时, 距边缘多少像素算"靠边"(准备翻页)

# ★ 应用运行期间左上角的「回桌面」返回区。
#   所有应用的返回键都在这一块（back_hit = [10,8,130,52]、
#   0..140/0..62、扫雷 (10,10,130,54)、我的世界 (0,0,150,58) …），
#   所以统一拦这一块最省事，也不会误伤：那一块本来就是"返回"。
EXIT_ZONE = (0, 0, 132, 58)
EDGE_DWELL = 0.55     # 靠边停留多久自动翻页(秒)

# ============ 图标 ============
#  设计原则 (参考 iPadOS / Material):
#    · 底块已经有颜色了, 所以图形本体用【白色/浅色】, 对比清晰
#    · 只用最简单的几何形, 一眼能认出来
#    · 全部按 s 的比例画, 换尺寸不变形
W = (255, 255, 255)          # 主色: 白
W2 = (226, 236, 252)         # 次色: 淡蓝白


def _cx(x, s):
    return x + s / 2.0


def icon_mines(d, x, y, s):
    """扫雷: 地雷 (圆 + 8 根刺 + 高光)"""
    cx, cy = x + s / 2.0, y + s / 2.0
    r = s * 0.26
    for a in range(0, 360, 45):
        dx = math.cos(math.radians(a)) * r * 1.55
        dy = math.sin(math.radians(a)) * r * 1.55
        d.line([cx, cy, cx + dx, cy + dy], fill=W, width=max(2, int(s * 0.075)))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=W)
    h = r * 0.42
    d.ellipse([cx - r * 0.45, cy - r * 0.62, cx - r * 0.45 + h, cy - r * 0.62 + h],
              fill=(120, 130, 155))


def icon_calc(d, x, y, s):
    """计算器: 圆角机身 + 显示屏 + 按键点"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w, h = s * 0.31, s * 0.40
    d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=W)
    d.rectangle([cx - w * 0.70, cy - h * 0.78, cx + w * 0.70, cy - h * 0.36],
                fill=(90, 105, 130))
    rr = s * 0.055
    for row in range(3):
        for col in range(3):
            px = cx - w * 0.66 + col * w * 0.66
            py = cy - h * 0.10 + row * h * 0.30
            d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=(120, 135, 160))


def icon_draw(d, x, y, s):
    """画板: 斜放的画笔"""
    # 笔杆
    d.line([x + s * 0.24, y + s * 0.76, x + s * 0.68, y + s * 0.28],
           fill=W, width=int(s * 0.13))
    # 笔尖
    d.polygon([(x + s * 0.24, y + s * 0.76),
               (x + s * 0.36, y + s * 0.64),
               (x + s * 0.18, y + s * 0.86)], fill=(255, 226, 130))
    # 笔杆末端的小方块
    d.rectangle([x + s * 0.62, y + s * 0.18, x + s * 0.80, y + s * 0.36], fill=W2)


def icon_files(d, x, y, s):
    """文件: 文件夹"""
    cx, cy = x + s / 2.0, y + s / 2.0 + s * 0.04
    w, h = s * 0.34, s * 0.27
    # 后面的标签
    d.rectangle([cx - w, cy - h * 1.55, cx - w * 0.15, cy - h * 0.75], fill=W2)
    # 主体
    d.rectangle([cx - w, cy - h * 0.95, cx + w, cy + h], fill=W)
    # 折痕
    d.line([cx - w * 0.62, cy - h * 0.30, cx + w * 0.62, cy - h * 0.30],
           fill=(120, 135, 160), width=max(1, int(s * 0.05)))


def icon_photo(d, x, y, s):
    """图片: 相框 + 山 + 太阳"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w, h = s * 0.36, s * 0.29
    d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=W)
    d.rectangle([cx - w * 0.82, cy - h * 0.80, cx + w * 0.82, cy + h * 0.80],
                fill=(108, 168, 226))
    sr = s * 0.075
    d.ellipse([cx + w * 0.20, cy - h * 0.50, cx + w * 0.20 + sr * 2,
               cy - h * 0.50 + sr * 2], fill=(255, 228, 120))
    d.polygon([(cx - w * 0.82, cy + h * 0.80), (cx - w * 0.10, cy - h * 0.05),
               (cx + w * 0.42, cy + h * 0.80)], fill=(74, 150, 96))


def icon_term(d, x, y, s):
    """命令面板: 终端 >_"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w, h = s * 0.37, s * 0.30
    d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=W)
    # ">"
    d.line([cx - w * 0.60, cy - h * 0.42, cx - w * 0.14, cy],
           fill=(60, 72, 96), width=max(2, int(s * 0.075)))
    d.line([cx - w * 0.14, cy, cx - w * 0.60, cy + h * 0.42],
           fill=(60, 72, 96), width=max(2, int(s * 0.075)))
    # 下划线
    d.line([cx - w * 0.02, cy + h * 0.42, cx + w * 0.58, cy + h * 0.42],
           fill=(60, 72, 96), width=max(2, int(s * 0.075)))


def icon_chip(d, x, y, s):
    """系统信息: 柱状图 (简洁, 一眼看出是"数据")"""
    cx, cy = x + s / 2.0, y + s / 2.0
    base = cy + s * 0.32
    bw = s * 0.14
    for i, hh in enumerate((0.26, 0.44, 0.34, 0.56)):
        px = cx - s * 0.34 + i * s * 0.225
        d.rectangle([px, base - s * hh, px + bw, base], fill=W)
    d.line([cx - s * 0.40, base + s * 0.02, cx + s * 0.40, base + s * 0.02],
           fill=W, width=max(2, int(s * 0.06)))


def icon_wifi(d, x, y, s):
    """WiFi: 三道弧 + 圆点"""
    cx, cy = x + s / 2.0, y + s * 0.72
    for r in (s * 0.46, s * 0.32, s * 0.18):
        d.arc([cx - r, cy - r, cx + r, cy + r], 215, 325, fill=W,
              width=max(2, int(s * 0.085)))
    rr = s * 0.075
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=W)


def icon_wall(d, x, y, s):
    """壁纸: 画框里的山景 (和"图片"区分: 这个带画框和挂绳)"""
    cx, cy = x + s / 2.0, y + s / 2.0 + s * 0.04
    w, h = s * 0.32, s * 0.25
    # 外层画框
    d.rectangle([cx - w - s * 0.06, cy - h - s * 0.06,
                 cx + w + s * 0.06, cy + h + s * 0.06], fill=W)
    # 画面
    d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=(126, 110, 200))
    d.polygon([(cx - w, cy + h), (cx - w * 0.25, cy - h * 0.15),
               (cx + w * 0.35, cy + h)], fill=(232, 236, 250))
    d.polygon([(cx - w * 0.05, cy + h), (cx + w * 0.45, cy - h * 0.35),
               (cx + w, cy + h)], fill=(190, 200, 240))
    sr = s * 0.065
    d.ellipse([cx + w * 0.30, cy - h * 0.70, cx + w * 0.30 + sr * 2,
               cy - h * 0.70 + sr * 2], fill=(255, 230, 140))
    # 挂绳
    d.line([cx, cy - h - s * 0.06, cx, cy - h - s * 0.17], fill=W,
           width=max(2, int(s * 0.05)))


def icon_info(d, x, y, s):
    """关于: 圆圈 i"""
    cx, cy = x + s / 2.0, y + s / 2.0
    r = s * 0.36
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=W)
    d.ellipse([cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72],
              fill=(96, 112, 148))
    sw = max(3, int(s * 0.095))
    d.line([cx, cy - r * 0.05, cx, cy + r * 0.48], fill=W, width=sw)
    d.ellipse([cx - sw / 2.0, cy - r * 0.50 - sw / 2.0,
               cx + sw / 2.0, cy - r * 0.50 + sw / 2.0], fill=W)


def icon_ai(d, x, y, s):
    """系统管家小白: 对话气泡 + 声波（代表"能听会说"）"""
    m = s * 0.08
    body = (86, 120, 246)
    d.rectangle([x + m, y + m, x + s - m, y + s * 0.66], fill=body)
    d.polygon([(x + s * 0.28, y + s * 0.65), (x + s * 0.48, y + s * 0.65),
               (x + s * 0.33, y + s * 0.86)], fill=body)
    cx = x + s / 2.0
    base = y + s * 0.365
    for i, hh in enumerate((0.09, 0.18, 0.27, 0.18, 0.09)):
        bx = cx + (i - 2) * s * 0.115
        d.line([bx, base - s * hh, bx, base + s * hh], fill=W,
               width=max(2, int(s * 0.055)))


def icon_gear(d, x, y, s):
    """设置: 齿轮（8 齿 + 中心孔）"""
    cx, cy = x + s / 2.0, y + s / 2.0
    col = (228, 232, 242)
    r = s * 0.30
    tw = s * 0.115
    # 8 个齿
    for i in range(8):
        a = math.pi * i / 4.0
        tx = cx + math.cos(a) * (r + tw * 0.45)
        ty = cy + math.sin(a) * (r + tw * 0.45)
        d.rectangle([tx - tw / 2, ty - tw / 2, tx + tw / 2, ty + tw / 2],
                    fill=col)
    # 轮体
    d.ellipse([cx - r * 1.12, cy - r * 1.12, cx + r * 1.12, cy + r * 1.12],
              fill=col)
    # 中心孔（比底色亮一点，显得是镂空）
    h = s * 0.125
    d.ellipse([cx - h, cy - h, cx + h, cy + h], fill=(70, 82, 110))


def icon_bell(d, x, y, s):
    """提示音: 铃铛"""
    cx, cy = x + s / 2.0, y + s / 2.0
    col = (255, 214, 90)
    body = s * 0.30
    # 铃身（梯形近似）
    d.polygon([(cx - body * 0.55, cy + body * 0.45),
               (cx - body, cy - body * 0.10),
               (cx - body * 0.72, cy - body * 0.72),
               (cx + body * 0.72, cy - body * 0.72),
               (cx + body, cy - body * 0.10),
               (cx + body * 0.55, cy + body * 0.45)], fill=col)
    # 底沿
    d.rectangle([cx - body * 1.18, cy + body * 0.40,
                 cx + body * 1.18, cy + body * 0.62], fill=col)
    # 顶钮
    d.ellipse([cx - s * 0.055, cy - body * 0.72 - s * 0.11,
               cx + s * 0.055, cy - body * 0.72 + s * 0.01], fill=col)
    # 铃舌
    d.ellipse([cx - s * 0.075, cy + body * 0.62,
               cx + s * 0.075, cy + body * 0.62 + s * 0.15], fill=col)
    # 右侧两道声波
    w = max(2, int(s * 0.045))
    for i, rr in enumerate((0.62, 0.80)):
        r = s * rr
        d.line([cx + r * 0.72, cy - r * 0.36, cx + r * 0.92, cy - r * 0.10],
               fill=(150, 220, 255), width=w)
        d.line([cx + r * 0.92, cy - r * 0.10, cx + r * 0.72, cy + r * 0.18],
               fill=(150, 220, 255), width=w)


def icon_music(d, x, y, s):
    """音乐: 音符"""
    cx, cy = x + s / 2.0, y + s / 2.0
    r = s * 0.135
    col = (255, 255, 255)
    # 符头
    d.ellipse([cx - s * 0.26 - r, cy + s * 0.16 - r,
               cx - s * 0.26 + r, cy + s * 0.16 + r], fill=col)
    d.ellipse([cx + s * 0.16 - r, cy + s * 0.06 - r,
               cx + s * 0.16 + r, cy + s * 0.06 + r], fill=col)
    # 符干
    w = max(2, int(s * 0.055))
    d.line([cx - s * 0.26 + r * 0.9, cy + s * 0.16,
            cx - s * 0.26 + r * 0.9, cy - s * 0.30], fill=col, width=w)
    d.line([cx + s * 0.16 + r * 0.9, cy + s * 0.06,
            cx + s * 0.16 + r * 0.9, cy - s * 0.40], fill=col, width=w)
    # 符梁
    d.polygon([(cx - s * 0.26 + r * 0.9, cy - s * 0.30),
               (cx + s * 0.16 + r * 0.9, cy - s * 0.40),
               (cx + s * 0.16 + r * 0.9, cy - s * 0.26),
               (cx - s * 0.26 + r * 0.9, cy - s * 0.16)], fill=col)


def icon_gpu(d, x, y, s):
    """GPU 加速: 芯片 + 闪电"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w = s * 0.31
    d.rectangle([cx - w, cy - w, cx + w, cy + w], fill=W)
    d.rectangle([cx - w * 0.62, cy - w * 0.62, cx + w * 0.62, cy + w * 0.62],
                fill=(122, 96, 190))
    # 引脚
    pw = max(2, int(s * 0.06))
    for i in range(3):
        o = -w + (i + 0.5) * (2 * w / 3.0)
        d.line([cx + o, cy - w, cx + o, cy - w - s * 0.11], fill=W, width=pw)
        d.line([cx + o, cy + w, cx + o, cy + w + s * 0.11], fill=W, width=pw)
        d.line([cx - w, cy + o, cx - w - s * 0.11, cy + o], fill=W, width=pw)
        d.line([cx + w, cy + o, cx + w + s * 0.11, cy + o], fill=W, width=pw)
    # 闪电
    z = s * 0.30
    d.polygon([(cx + z * 0.20, cy - z), (cx - z * 0.62, cy + z * 0.12),
               (cx - z * 0.06, cy + z * 0.12), (cx - z * 0.22, cy + z),
               (cx + z * 0.62, cy - z * 0.16), (cx + z * 0.06, cy - z * 0.16)],
              fill=(255, 214, 60))


def icon_scope(d, x, y, s):
    """示波器: 屏幕框 + 里面一条正弦波"""
    m = s * 0.10
    d.rectangle([x + m, y + m, x + s - m, y + s - m],
                outline=W, width=max(2, int(s * 0.055)))
    pw = max(2, int(s * 0.065))
    pts = []
    n = 28
    for i in range(n + 1):
        t = i / float(n)
        px = x + m * 1.9 + t * (s - m * 3.8)
        py = y + s / 2.0 - (s * 0.27) * math.sin(2 * math.pi * t)
        pts.append((px, py))
    d.line(pts, fill=(110, 255, 190), width=pw)
    # 一条触发电平虚线
    ty = y + s * 0.34
    for i in range(4):
        px = x + m * 2.2 + i * s * 0.18
        d.line([(px, ty), (px + s * 0.10, ty)], fill=(255, 176, 64), width=2)


def icon_browser(d, x, y, s):
    """浏览器: 地球 + 经纬线"""
    cx, cy = x + s / 2.0, y + s / 2.0
    r = s * 0.36
    w = max(2, int(s * 0.055))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=W, width=w)
    d.ellipse([cx - r * 0.44, cy - r, cx + r * 0.44, cy + r], outline=W2, width=max(1, w - 1))
    d.line([cx - r, cy, cx + r, cy], fill=W2, width=max(1, w - 1))
    d.line([cx - r * 0.86, cy - r * 0.5, cx + r * 0.86, cy - r * 0.5],
           fill=W2, width=max(1, w - 1))
    d.line([cx - r * 0.86, cy + r * 0.5, cx + r * 0.86, cy + r * 0.5],
           fill=W2, width=max(1, w - 1))


def icon_novel(d, x, y, s):
    """小说: 摊开的书 + 文字行"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w, h = s * 0.36, s * 0.28
    for sgn in (-1, 1):
        d.polygon([(cx + sgn * w, cy - h * 0.85),
                   (cx + sgn * w * 0.06, cy - h * 0.55),
                   (cx + sgn * w * 0.06, cy + h * 1.05),
                   (cx + sgn * w, cy + h * 0.75)], fill=W)
    d.line([cx, cy - h * 0.55, cx, cy + h * 1.05], fill=(120, 135, 160),
           width=max(1, int(s * 0.045)))
    for k in range(3):
        yy = cy - h * 0.16 + k * h * 0.38
        d.line([cx - w * 0.78, yy, cx - w * 0.24, yy], fill=(142, 158, 186),
               width=max(1, int(s * 0.038)))
        d.line([cx + w * 0.24, yy, cx + w * 0.78, yy], fill=(142, 158, 186),
               width=max(1, int(s * 0.038)))


def icon_fight(d, x, y, s):
    """格斗: 两把交叉的刀 (橙=火影, 银白=死神)"""
    cx, cy = x + s / 2.0, y + s / 2.0
    L = s * 0.40
    for sgn, col in ((-1, (255, 152, 62)), (1, (232, 238, 248))):
        a = sgn * 0.66
        dx, dy = math.sin(a) * L, -math.cos(a) * L
        w = max(3, int(s * 0.085))
        d.line([cx - dx, cy - dy, cx + dx, cy + dy], fill=(20, 22, 34), width=w + 3)
        d.line([cx - dx, cy - dy, cx + dx, cy + dy], fill=col, width=w)
        tx, ty = cx + dx, cy + dy          # 刀尖
        d.polygon([(tx + dy * 0.15, ty - dx * 0.15),
                   (tx + dx * 0.15, ty + dy * 0.15),
                   (tx - dy * 0.15, ty + dx * 0.15)], fill=col)
    r = s * 0.105
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(22, 24, 36))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=W)
    d.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], fill=(48, 52, 70))


def icon_mc(d, x, y, s):
    """MC: 等距草方块 (经典 Minecraft 方块)"""
    cx, cy = x + s / 2.0, y + s / 2.0
    w = s * 0.40
    h = s * 0.235
    dtop = (118, 196, 84)
    dfront = (150, 116, 78)
    dright = (108, 82, 54)
    edge = (26, 34, 22)
    # 顶面
    d.polygon([(cx, cy - h * 1.6), (cx + w, cy - h * 0.6),
               (cx, cy + h * 0.4), (cx - w, cy - h * 0.6)], fill=dtop, outline=edge)
    # 左面(前)
    d.polygon([(cx - w, cy - h * 0.6), (cx, cy + h * 0.4),
               (cx, cy + h * 1.5), (cx - w, cy + h * 0.5)], fill=dfront, outline=edge)
    # 右面
    d.polygon([(cx + w, cy - h * 0.6), (cx, cy + h * 0.4),
               (cx, cy + h * 1.5), (cx + w, cy + h * 0.5)], fill=dright, outline=edge)
    # 草皮垂下来的边
    d.polygon([(cx - w, cy - h * 0.6), (cx, cy + h * 0.4), (cx + w, cy - h * 0.6),
               (cx + w, cy - h * 0.6 + h * 0.22), (cx, cy + h * 0.4 + h * 0.22),
               (cx - w, cy - h * 0.6 + h * 0.22)], fill=dtop)


APPS = [
    {"name": "系统管家小白", "mod": "apps_agent", "icon": icon_ai, "tint": (86, 120, 246)},
    {"name": "设置",     "mod": "apps_settings", "icon": icon_gear, "tint": (120, 124, 136)},
    {"name": "提示音",   "mod": "apps_chime", "icon": icon_bell, "tint": (240, 180, 60)},
    {"name": "音乐",     "mod": "apps_music", "icon": icon_music, "tint": (235, 120, 170)},
    {"name": "示波器",   "mod": "apps_scope", "icon": icon_scope, "tint": (60, 180, 150)},
    {"name": "我的世界", "mod": "apps_mc", "icon": icon_mc, "tint": (96, 170, 88)},
    {"name": "死神VS火影", "mod": "apps_fight", "icon": icon_fight, "tint": (235, 92, 84)},
    {"name": "扫雷",     "mod": "apps_mines", "icon": icon_mines, "tint": (225, 80, 70)},
    {"name": "计算器",   "mod": "apps_calc",  "icon": icon_calc,  "tint": (240, 160, 50)},
    {"name": "画板",     "mod": "apps_draw",  "icon": icon_draw,  "tint": (60, 195, 150)},
    {"name": "文件",     "mod": "apps_files", "icon": icon_files, "tint": (90, 150, 240)},
    {"name": "图片",     "mod": "apps_view",  "icon": icon_photo, "tint": (165, 110, 235)},
    {"name": "小说",     "mod": "apps_novel", "icon": icon_novel, "tint": (188, 140, 78)},
    {"name": "浏览器",   "mod": "apps_browser", "icon": icon_browser, "tint": (72, 156, 214)},
    {"name": "命令面板", "mod": "apps_term",  "icon": icon_term,  "tint": (95, 125, 165)},
    {"name": "GPU 测试台", "mod": "apps_gpu", "icon": icon_gpu,   "tint": (200, 90, 210)},
    {"name": "系统信息", "mod": "apps_sys",   "icon": icon_chip,  "tint": (70, 190, 205)},
    {"name": "WiFi",     "mod": "apps_wifi",  "icon": icon_wifi,  "tint": (70, 150, 245)},
    {"name": "壁纸",     "mod": "apps_wallpaper", "icon": icon_wall, "tint": (235, 120, 170)},
    {"name": "关于",     "mod": "apps_about", "icon": icon_info,  "tint": (130, 145, 175)},
]
COLS = 6            # 桌面图标列数 (6列x2行=12格, 放得下11个应用)
MENU_COLS = 2       # 开始菜单列数

# ============ 桌面 ============
class Desktop:
    ORDER_FILE = "/home/zynq/.desktop_order"
    PAGES_FILE = "/home/zynq/.desktop_pages"   # 多页面布局 (JSON)
    GPU_MARKER = "/home/zynq/.gpu_addr"      # 内容如 "0x43CB0000"; 存在才【敢探测】
    GPU_DESKTOP_FLAG = "/home/zynq/.gpu_desktop"   # 存在才让【桌面】用 GPU 渲染
    WALL_CONF = "/home/zynq/.wallpaper"      # 内容是一张图片的路径; 没有则用内置壁纸

    def __init__(self):
        self.scr = Screen()
        self.touch = Touch()
        self.pages = self.load_pages()        # ★ 多页面布局
        self.page = 0                         # 当前页
        self.apps = self.all_apps()           # 扁平列表 (开始菜单用)
        self.swipe_x = None                   # 翻页手势起点
        self.swipe_y = None
        self.swipe_t = 0.0
        self.edge_t = 0.0                     # 拖动时停在边缘的计时
        self.wall = self.load_wallpaper()
        self._wall_stamp = self.wall_stamp()
        self.menu_open = False
        self.last_clock = ""
        self.cpu = 0
        self.last_cpu_t = 0
        self._cpu_prev = None
        # 交互状态
        self.drag = None          # 正在拖动的应用
        self.drag_pos = (0, 0)
        self.drag_from = -1
        self.drag_from_page = 0
        self.press_t = 0.0
        self.down_xy = None       # 落笔位置 (判断是点击还是拖动)
        self.grab_off = (0, 0)    # 手指抓住图标的相对位置 (拖动时不跳动)
        self._bg = None           # 拖动快路径用的背景缓存
        self.pressed = None
        self.anim = None          # 启动动画
        self.try_gpu()
        # ---- 卡片首页 (P1): 首页 = 第 0 屏, 图标网格 = 后面的屏 ----
        self.at_home = True
        self.home = None
        self._init_home()

    # ==================== 卡片首页 ====================
    def _init_home(self):
        """加载卡片首页; 出任何问题都退回图标网格, 绝不让桌面起不来"""
        try:
            import home as _home
            self.home = _home.Home(self.scr, apps=self.all_apps(),
                                   icons={a["name"]: a["icon"] for a in APPS})
            self.home.wall = self.wall
            self.home.n_pages = self.total_pages()
            print("卡片首页已加载")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print("首页模块不可用, 退回图标网格:", ex)
            self.home = None
            self.at_home = False

    def total_pages(self):
        """总屏数 = 卡片首页 + 图标页"""
        return (1 if self.home is not None else 0) + self.page_count()

    def by_name(self, name):
        for a in APPS:
            if a["name"] == name:
                return a
        return None

    def go_home(self, on=True):
        if self.home is None:
            return
        self.at_home = bool(on)
        self.menu_open = False
        self.draw()

    def redraw_home(self):
        self.home.page = 0
        self.home.n_pages = self.total_pages()
        self.home.apps = self.all_apps()
        self.home.draw()

    def dock_action(self, v):
        print("[dock]", v)
        if v == "home":
            self.go_home(True)
        elif v == "apps":
            if self.at_home:
                self.at_home = False
                self.draw()
            else:
                self.menu_open = True
                self.draw()
        elif v == "settings":
            # ★ 原来写的是 by_name("系统信息") or by_name("设置")，
            #   所以 Dock「设置」其实打开的是"系统信息"。现在有真正的设置 App 了，
            #   要优先它（"系统信息" 作为兜底）。
            a = self.by_name("设置") or self.by_name("系统信息")
            if a:
                self.run_app(a)
        else:
            name = {"novel": "小说", "browser": "浏览器", "music": "音乐"}.get(v, v)
            a = self.by_name(name)
            if a:
                self.run_app(a)
            else:
                self.toast("「%s」还没做 —— 排在后面的阶段" % name)

    def card_action(self, key):
        if key == "system":
            a = self.by_name("系统信息")
        elif key == "network":
            a = self.by_name("WiFi")
        elif key == "weather":
            # ★ 原来 "weather" 和 "network" 被写在同一个分支里，点天气会跳到 WiFi。
            #   正确行为：卡片上有天气数据 -> 刷新 + 弹详情；
            #   卡片上写的是"未联网 / 点这里设置 WiFi" -> 才去开 WiFi。
            if self.home is not None and self.home.info.weather:
                self.show_weather()
                return
            a = self.by_name("WiFi")
        elif key == "music":
            self.dock_action("music")
            return
        else:
            return
        if a:
            self.run_app(a)

    def show_weather(self):
        """点天气卡：重新抓一次天气，然后把详情弹出来"""
        H = getattr(self, "home", None)
        if H is None:
            return
        info = H.info
        try:
            info.tick(True)              # 强制全量刷新（含天气）
        except Exception:
            pass
        try:
            H.draw()                     # 卡片上的字跟着更新
        except Exception:
            pass
        w = info.weather or {}
        if not w:
            print("[weather] 点天气卡: 没有数据，提示稍后再试")
            self.toast("天气暂时读不到（网络不通？）", 1.8)
            return
        parts = ["%s %s°C %s" % (w.get("city", ""), w.get("temp", ""),
                                 w.get("text", ""))]
        if w.get("hi") is not None:
            parts.append("最高 %s° 最低 %s°" % (w.get("hi"), w.get("lo")))
        if w.get("hum"):
            parts.append("湿 %s%%" % w["hum"])
        if w.get("age"):
            parts.append(str(w["age"]))
        print("[weather] 点天气卡: 刷新并弹详情 ->", "   ".join(parts))
        self.toast("   ".join(parts), 2.4)

    def toast(self, msg, secs=1.6):
        """居中提示条; 结束后把那一块精确还原 (静态层 + 动态内容)"""
        scr = self.scr
        w = int(scr.tw(msg, 20, cn=True)) + 60
        w = min(w, 1024 - 24)          # ★ 太长的消息别冲出屏幕
        x0 = (1024 - w) // 2
        y0, y1 = 258, 336
        scr.rrect([x0, y0, x0 + w, y1], 18, fill=(28, 36, 60),
                  outline=(92, 116, 158), width=2)
        scr.text((512, (y0 + y1) // 2), msg, 20, (240, 245, 255), cn=True, anchor="mm")
        scr.flush([x0 - 6, y0 - 6, x0 + w + 6, y1 + 6])
        time.sleep(secs)
        box = (max(0, x0 - 6), max(0, y0 - 6), min(1024, x0 + w + 6), min(600, y1 + 6))
        if self.at_home and self.home is not None:
            self.home.restore(box)
        else:
            self.draw()

    # ---- 图标顺序持久化 / 多页面布局 ----
    #   pages = [ [名字或None, ...12格], [..], ... ]   (6列 x 2行 = 12 格/页)
    def load_pages(self):
        byname = {a["name"]: a for a in APPS}
        n_slots = COLS * 2
        pages = []
        # 1) 读页面文件
        try:
            import json
            data = json.load(open(self.PAGES_FILE))
            for pg in data:
                row = []
                for n in list(pg)[:n_slots]:
                    row.append(n if n in byname else None)
                while len(row) < n_slots:
                    row.append(None)
                pages.append(row)
        except Exception:
            pass
        # 2) 没文件 -> 按旧的 .desktop_order 排序, 再自动分页 (老用户平滑升级)
        if not pages:
            order = []
            try:
                order = [n for n in open(self.ORDER_FILE).read().split("\n")
                         if n in byname]
            except Exception:
                pass
            for a in APPS:
                if a["name"] not in order:
                    order.append(a["name"])
            for i in range(0, max(1, len(order)), n_slots):
                chunk = order[i:i + n_slots]
                pages.append(chunk + [None] * (n_slots - len(chunk)))
        # 3) 新增的应用(APPS 里加了但页面上没有) -> 补到第一个空位, 没有就开新页
        placed = set(n for pg in pages for n in pg if n)
        for a in APPS:
            if a["name"] in placed:
                continue
            for pg in pages:
                if None in pg:
                    pg[pg.index(None)] = a["name"]
                    placed.add(a["name"])
                    break
            else:
                pg = [None] * n_slots
                pg[0] = a["name"]
                pages.append(pg)
                placed.add(a["name"])
        if not pages:
            pages = [[None] * n_slots]
        # 4) 至少保证 2 页, 这样总有空位可以放图标 (用户体验上很重要)
        while len(pages) < 2:
            pages.append([None] * n_slots)
        return pages

    def save_pages(self):
        import json
        try:
            with open(self.PAGES_FILE, "w") as f:
                json.dump(self.pages, f, ensure_ascii=False)
        except Exception as ex:
            print("保存页面布局失败:", ex)

    def all_apps(self):
        """所有应用 (按页面顺序, 给开始菜单用)"""
        byname = {a["name"]: a for a in APPS}
        out = []
        for pg in self.pages:
            for n in pg:
                if n and n in byname:
                    out.append(byname[n])
        return out

    def refresh_apps(self):
        self.apps = self.all_apps()

    def load_order(self):
        """兼容老接口: 返回扁平的应用列表"""
        return self.all_apps()

    def save_order(self):
        self.save_pages()

    def try_gpu(self):
        """桌面【默认不使用】FPGA GPU, 只在 .gpu_desktop 标记存在时才挂载

        ★ 这里有两个不同的标记, 别混:

          .gpu_addr    —— "这个 bitstream 里确实有 GPU, 地址是 0x43CB0000"
                          它只用来判断【探测安不安全】。
                          为什么不能盲目探测: 探测要 mmap /dev/mem 并读寄存器,
                          如果该地址在当前 bitstream 里没被解码, ARM 会触发
                          **SIGBUS** 直接杀进程 —— Python 的 try/except 抓不住信号,
                          整个桌面会崩并被 systemd 反复重启。

          .gpu_desktop —— "让桌面用 GPU 画东西", 默认【不存在】。

        为什么默认不用:
          实测 (真机数据见 06_文档/自研GPU_1字节每拍根因与64位修复.md):
            · 整屏填充  GPU 2.614 ms (705 MB/s)  vs  CPU C 填充器 0.995 ms (1853 MB/s)
            · 小矩形    GPU 3.122 ms (69个)      vs  CPU 1.092 ms
          PL 的 AXI 主口只有 100 MHz, 64 位 × 100 MHz = 800 MB/s 是硬天花板,
          而一个 Cortex-A9 核用 NEON 能到 1853 MB/s。桌面上全是小矩形,
          GPU 更吃亏 (每个矩形一次寄存器往返)。所以桌面用软件渲染反而更快。

          GPU 现在是一个【测试/演示程序】(桌面上的 "GPU 测试台" 图标),
          需要演示时才打开, 平常不参与日常渲染。
        """
        import os
        if not os.path.exists(self.GPU_DESKTOP_FLAG):
            print("GPU: 桌面默认不用 GPU (没有 %s), 使用软件渲染"
                  % self.GPU_DESKTOP_FLAG)
            return
        try:
            addr = int(open(self.GPU_MARKER).read().strip(), 0)
        except Exception:
            print("GPU: 未集成 (缺 %s), 使用软件渲染" % self.GPU_MARKER)
            return
        try:
            from gpu import GPU
            g = GPU(addr, verbose=False)
            if g.probe():
                self.scr.attach_gpu(g)
                print("FPGA GPU 已挂载 @0x%08X ✅" % addr)
            else:
                g.close()
                print("GPU: 0x%08X 无响应 (bitstream 不对?)" % addr)
        except Exception as ex:
            print("GPU 挂载失败:", ex)

    # ---- 壁纸 ----
    def glow(self, d, cx, cy, r, base, steps=26):
        for i in range(steps, 0, -1):
            t = i / float(steps)
            rr = int(r * t)
            c = tuple(int(base[j] * (1 - t) + C_BOT[j] * t) for j in range(3))
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=c)

    def fit_image(self, path):
        """把图片缩放/裁剪成 1024x600 (保持比例, 居中裁剪)"""
        im = Image.open(path).convert("RGB")
        iw, ih = im.size
        if iw == self.scr.w and ih == self.scr.h:
            return im
        sc = max(self.scr.w / float(iw), self.scr.h / float(ih))
        im = im.resize((max(1, int(iw * sc)), max(1, int(ih * sc))), Image.LANCZOS)
        iw, ih = im.size
        l = max(0, (iw - self.scr.w) // 2)
        t = max(0, (ih - self.scr.h) // 2)
        return im.crop((l, t, l + self.scr.w, t + self.scr.h))

    def load_wallpaper(self):
        """读 ~/.wallpaper 指定的图片; 没有/读不到就用内置渐变壁纸"""
        if not os.path.exists(self.WALL_CONF):
            return self.make_wallpaper()          # 没设过 -> 内置(正常情况)
        try:
            p = open(self.WALL_CONF).read().strip()
            if p and os.path.isfile(p):
                return self.fit_image(p)
            print("壁纸文件不存在: %s" % p)
        except Exception as ex:
            print("壁纸加载失败(%s), 用内置的" % ex)
        return self.make_wallpaper()

    def wall_stamp(self):
        """壁纸配置的修改时间, 用来判断"壁纸变了没有" """
        try:
            return os.stat(self.WALL_CONF).st_mtime
        except Exception:
            return 0

    def make_wallpaper(self):
        im = Image.new("RGB", (1024, 600), C_BOT)
        d = ImageDraw.Draw(im)
        for y in range(600):
            t = y / 600.0
            t = t ** 0.85
            d.line([(0, y), (1024, y)],
                   fill=(int(C_TOP[0] + (C_BOT[0] - C_TOP[0]) * t),
                         int(C_TOP[1] + (C_BOT[1] - C_TOP[1]) * t),
                         int(C_TOP[2] + (C_BOT[2] - C_TOP[2]) * t)))
        # 光晕
        self.glow(d, 130, 90, 300, (52, 96, 190))
        self.glow(d, 950, 540, 300, (36, 78, 150))
        self.glow(d, 780, 120, 200, (90, 60, 160))
        # 网格
        for x in range(0, 1024, 64):
            d.line([(x, 0), (x, 600)], fill=(24, 33, 58))
        for y in range(0, 600, 64):
            d.line([(0, y), (1024, y)], fill=(24, 33, 58))
        # 水印芯片
        d.rectangle([820, 400, 1000, 560], outline=(60, 92, 150), width=3)
        d.rectangle([860, 440, 960, 520], outline=(60, 92, 150), width=2)
        for i in range(3):
            o = 840 + i * 40
            d.line([(o, 400), (o, 370)], fill=(60, 92, 150), width=3)
            d.line([(o, 560), (o, 590)], fill=(60, 92, 150), width=3)
        # 标题
        from fbui import font as F
        d.text((52, 20), "Zynq-7020", font=F(30, bold=True), fill=(150, 185, 245))
        d.text((52, 56), "嵌入式小电脑", font=F(18, cn=True), fill=(120, 148, 200))
        return im

    # ---- 布局 / 多页面 ----
    def page_count(self):
        return max(1, len(self.pages))

    def goto_page(self, n):
        n = max(0, min(self.page_count() - 1, n))
        if n != self.page:
            self.page = n
            print("切到第 %d 页" % (n + 1))
            self.draw()

    def add_page(self):
        """新增一页 (平板的"＋"页)。最后一页还是空的就不给再建, 免得一堆空页"""
        n_slots = COLS * 2
        if self.pages and not any(self.pages[-1]):
            print("最后一页还是空的, 不再新建")
            return
        self.pages.append([None] * n_slots)
        self.save_pages()
        print("新增一页, 共 %d 页" % len(self.pages))
        self.goto_page(len(self.pages) - 1)

    def grid(self):
        """当前页的格子。最后一页多给一个"＋"格用于新建页面"""
        total_w = COLS * ICON_W + (COLS - 1) * GAP_X
        ox = (1024 - total_w) // 2
        out = []
        byname = {a["name"]: a for a in APPS}
        pg = self.pages[self.page] if self.page < len(self.pages) else []
        for i in range(COLS * 2):
            col, row = i % COLS, i // COLS
            x = ox + col * (ICON_W + GAP_X)
            y = ICON_TOP + row * (ICON_H + GAP_Y)
            name = pg[i] if i < len(pg) else None
            a = byname.get(name)
            out.append((x, y, x + ICON_W, y + ICON_H, a))
        return out

    def slot_at(self, x, y):
        """返回坐标落在当前页第几个格子(不在格子上返回 -1)"""
        for i, (x0, y0, x1, y1, a) in enumerate(self.grid()):
            if x0 - 8 <= x <= x1 + 8 and y0 - 8 <= y <= y1 + 8:
                return i
        return -1

    def move_app(self, from_page, from_slot, to_page, to_slot):
        """把一个应用从 (页,格) 移到 (页,格); 目标有应用就交换"""
        while to_page >= len(self.pages):
            self.pages.append([None] * (COLS * 2))
        a = self.pages[from_page][from_slot]
        b = self.pages[to_page][to_slot]
        self.pages[to_page][to_slot] = a
        if from_page == to_page:
            self.pages[from_page][from_slot] = b
        else:
            # 跨页移动: 原位留空 (目标位的应用放到源位空档, 更像平板)
            self.pages[from_page][from_slot] = b
        self.save_pages()
        self.refresh_apps()

    def draw_dots(self):
        """底部页码小圆点 (当前页大而亮, 其它页小而淡)"""
        n = self.page_count()
        if n <= 1:
            return
        scr = self.scr
        gap = 26
        total = n * gap
        x0 = (1024 - total) // 2 + gap // 2
        y = 600 - TB_H - 24
        for i in range(n):
            cx = x0 + i * gap
            if i == self.page:
                r = 7
                scr.d.ellipse([cx - r - 2, y - r - 2, cx + r + 2, y + r + 2],
                              fill=(20, 26, 40))          # 深色描边
                scr.d.ellipse([cx - r, y - r, cx + r, y + r], fill=(255, 255, 255))
            else:
                r = 4
                scr.d.ellipse([cx - r - 1, y - r - 1, cx + r + 1, y + r + 1],
                              fill=(20, 26, 40))
                scr.d.ellipse([cx - r, y - r, cx + r, y + r], fill=(180, 195, 225))

    def draw_icon(self, a, x0, y0, pressed=False, alpha_bg=None):
        """平板风格图标: 圆角"磨砂玻璃"方块 + 每个应用自己的色调 + 下方白字标签"""
        scr = self.scr
        x1, y1 = x0 + ICON_W, y0 + ICON_H
        tint = a.get("tint", (70, 110, 170))
        if pressed:
            fill = tuple(min(255, int(c * 0.55 + 90)) for c in tint)
            edge = (235, 245, 255)
        else:
            # 深色玻璃底 + 该应用的色相 (像平板的毛玻璃图标)
            fill = (int(tint[0] * 0.34 + 18), int(tint[1] * 0.34 + 22), int(tint[2] * 0.34 + 34))
            edge = tuple(int(c * 0.62 + 40) for c in tint)
        # 主体圆角方块
        scr.rrect([x0, y0, x1, y1], 22, fill=fill, outline=edge, width=2)
        # 顶部高光 (玻璃反光感)
        hl = tuple(min(255, int(c * 0.5 + 46)) for c in fill)
        scr.rrect([x0 + 5, y0 + 4, x1 - 5, y0 + 4 + 20], 12, fill=hl)
        # 图标本体 (居中)
        gs = int(ICON_W * 0.56)
        gx = x0 + (ICON_W - gs) // 2
        gy = y0 + (ICON_H - gs) // 2 + 2
        try:
            a["icon"](scr.d, gx, gy, gs)
        except Exception:
            pass
        # 文字标签: 先画一圈深色描边(阴影), 再画白字 -> 任何壁纸上都清楚
        cx = (x0 + x1) // 2
        ty = y1 + 8
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)):
            scr.text((cx + dx, ty + dy), a["name"], 19, (8, 12, 24), cn=True, anchor="ma")
        scr.text((cx, ty), a["name"], 19, (250, 252, 255), cn=True, anchor="ma")

    def menu_rect(self):
        rows = (len(self.apps) + MENU_COLS - 1) // MENU_COLS
        h = 52 + rows * 46 + 14
        w = 20 + MENU_COLS * 300
        return [10, 600 - TB_H - h - 6, 10 + w, 600 - TB_H - 6]

    def menu_cells(self):
        """开始菜单的每个格子(按列填充, 两列)"""
        r = self.menu_rect()
        rows = (len(self.apps) + MENU_COLS - 1) // MENU_COLS
        cw = (r[2] - r[0] - 16) // MENU_COLS
        out = []
        for i, a in enumerate(self.apps):
            col, row = i // rows, i % rows
            x = r[0] + 8 + col * cw
            y = r[1] + 52 + row * 46
            out.append(([x, y, x + cw - 8, y + 42], a))
        return out

    def tb_rect(self):
        return [0, 600 - TB_H, 1024, 600]

    # ---- 绘制 ----
    def _drag_rect(self):
        """拖动中图标当前占的矩形 (含标签, 留点余量)"""
        dx, dy = self.drag_pos
        ox, oy = getattr(self, "grab_off", (0, 0))
        x0 = dx - ox - ICON_W // 2
        y0 = dy - oy - ICON_H // 2
        return [x0 - 6, y0 - 6, x0 + ICON_W + 6, y0 + ICON_H + 34]

    def draw(self, pressed=None, fast=None):
        scr = self.scr

        # 壁纸被换掉 -> 首页的静态层也要重建
        H = getattr(self, "home", None)
        if H is not None and H.wall is not self.wall:
            H.wall = self.wall
            H.static = None

        # ★ 拖动快路径: 只重画拖动图标那一小块 (整屏重绘 ~40ms, 局部 ~2ms)
        if (fast is not None and self.drag is not None
                and getattr(self, "_bg", None) is not None and not self.at_home):
            scr.img.paste(self._bg)
            scr.d = ImageDraw.Draw(scr.img)
            # ★ 补画"原位占位框" —— 背景缓存是拖动开始前存的, 里面还有原来那个图标,
            #   不补画的话屏幕上会同时出现两个同样的图标 (看起来像"幽灵")
            if (self.drag_from_page == self.page
                    and 0 <= self.drag_from < COLS * 2):
                g = self.grid()[self.drag_from]
                scr.rrect([g[0], g[1], g[2], g[3]], 22, fill=(30, 42, 70),
                          outline=(120, 150, 200), width=2)
            dx, dy = self.drag_pos
            ox, oy = getattr(self, "grab_off", (0, 0))
            self.draw_icon(self.drag, dx - ox - ICON_W // 2, dy - oy - ICON_H // 2,
                           pressed=True)
            # 占位框所在的格子也要刷到 (可能不在 fast 矩形里)
            if (self.drag_from_page == self.page
                    and 0 <= self.drag_from < COLS * 2):
                g = self.grid()[self.drag_from]
                fast = [min(fast[0], g[0] - 8), min(fast[1], g[1] - 8),
                        max(fast[2], g[2] + 8), max(fast[3], g[3] + 36)]
            scr.flush(fast)
            return

        scr.img.paste(self.wall)
        scr.d = ImageDraw.Draw(scr.img)

        # ★★ 卡片首页
        if self.at_home and H is not None:
            H.page = 0
            H.n_pages = self.total_pages()
            H.apps = self.all_apps()
            H.draw(full=True)
            if self.menu_open:
                self.draw_menu()
                scr.flush()
            try:
                self._bg = scr.img.copy()
            except Exception:
                self._bg = None
            return

        is_last = (self.page == self.page_count() - 1)
        free = self._free_slots()
        plus_slot = free[-1] if (is_last and free) else -1   # "＋"放在最后一个空位
        for i, (x0, y0, x1, y1, a) in enumerate(self.grid()):
            if a is None:
                if i == plus_slot:
                    self._draw_plus(x0, y0)
                continue
            if self.drag is not None and a is self.drag:
                # 原位置画个虚线框(占位)
                scr.rrect([x0, y0, x1, y1], 22, fill=(30, 42, 70),
                          outline=(120, 150, 200), width=2)
                continue
            self.draw_icon(a, x0, y0, pressed=(pressed == a["name"]))

        # 拖动中的图标跟着手指 (保持抓取时的相对位置, 不跳动)
        if self.drag is not None:
            dx, dy = self.drag_pos
            ox, oy = getattr(self, "grab_off", (0, 0))
            self.draw_icon(self.drag, dx - ox - ICON_W // 2, dy - oy - ICON_H // 2,
                           pressed=True)
            self._draw_edge_hint()

        if H is not None and not self.menu_open:
            # 图标页也复用新外壳: 顶部状态栏 + 底部 Dock + 页码点
            H.page = 1 + self.page
            H.n_pages = self.total_pages()
            H.draw_chrome(scr)
        else:
            self.draw_dots()
            self.draw_taskbar()
        if self.menu_open:
            self.draw_menu()
        scr.flush()
        # 存一份"没有拖动图标"的背景, 给拖动快路径用
        try:
            self._bg = scr.img.copy()
        except Exception:
            self._bg = None

    def _free_slots(self):
        """当前页所有空位的下标"""
        pg = self.pages[self.page] if self.page < len(self.pages) else []
        out = []
        for i in range(COLS * 2):
            if i >= len(pg) or pg[i] is None:
                out.append(i)
        return out

    def _first_free_slot(self):
        f = self._free_slots()
        return f[0] if f else -1

    def _draw_plus(self, x0, y0):
        """新建页面的"＋"块"""
        scr = self.scr
        x1, y1 = x0 + ICON_W, y0 + ICON_H
        scr.rrect([x0, y0, x1, y1], 22, fill=(34, 40, 58),
                  outline=(120, 140, 175), width=2)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        scr.d.rectangle([cx - 20, cy - 3, cx + 20, cy + 3], fill=(190, 205, 235))
        scr.d.rectangle([cx - 3, cy - 20, cx + 3, cy + 20], fill=(190, 205, 235))
        scr.text((cx, y1 + 8), "新建页面", 19, (200, 215, 240), cn=True, anchor="ma")

    def _draw_edge_hint(self):
        """拖动到边缘时画一个"翻页"提示 (箭头 + 进度)"""
        if self.edge_t <= 0:
            return
        scr = self.scr
        x, y = self.drag_pos
        t = min(1.0, (time.time() - self.edge_t) / EDGE_DWELL)
        if x < EDGE_ZONE and self.page > 0:
            cx = 36
            left = True
        elif x > 1024 - EDGE_ZONE and self.page < self.page_count() - 1:
            cx = 1024 - 36
            left = False
        else:
            return
        cy = 300
        # 半透明底
        scr.d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=(20, 28, 46))
        scr.d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], outline=(120, 170, 235), width=2)
        # 进度弧 (用扇形近似)
        scr.d.pieslice([cx - 30, cy - 30, cx + 30, cy + 30], -90, -90 + int(360 * t),
                       fill=(70, 130, 210))
        scr.d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=(20, 28, 46))
        # 箭头
        col = (240, 248, 255)
        s = 11
        if left:
            scr.d.polygon([(cx - s, cy), (cx + s, cy - s), (cx + s, cy + s)], fill=col)
        else:
            scr.d.polygon([(cx + s, cy), (cx - s, cy - s), (cx - s, cy + s)], fill=col)

    def draw_taskbar(self):
        scr = self.scr
        y0 = 600 - TB_H
        for i in range(TB_H):
            t = i / float(TB_H)
            scr.d.line([(0, y0 + i), (1024, y0 + i)],
                       fill=(int(C_TASKBAR2[0] + (C_TASKBAR1[0] - C_TASKBAR2[0]) * t),
                             int(C_TASKBAR2[1] + (C_TASKBAR1[1] - C_TASKBAR2[1]) * t),
                             int(C_TASKBAR2[2] + (C_TASKBAR1[2] - C_TASKBAR2[2]) * t)))
        scr.rect([0, y0, 1024, y0 + 2], fill=C_LINE)
        scr.rrect([12, y0 + 10, 116, y0 + TB_H - 10], 10,
                  fill=C_ACCENT if self.menu_open else (42, 76, 140))
        scr.text((64, y0 + TB_H // 2), "开始", 20, (255, 255, 255), cn=True, anchor="mm")
        scr.text((134, y0 + TB_H // 2), "Zynq Desktop", 19, C_TEXT_DIM, anchor="lm")
        # 状态
        scr.text((660, y0 + TB_H // 2), "CPU %d%%" % self.cpu, 17, (150, 200, 240),
                 anchor="lm", mono=True)
        scr.text((766, y0 + TB_H // 2), self.mem_str(), 17, (150, 200, 240),
                 anchor="lm", mono=True)
        if self.scr.gpu is not None:
            scr.rrect([860, y0 + 14, 916, y0 + TB_H - 14], 6, fill=(46, 140, 90))
            scr.text((888, y0 + TB_H // 2), "GPU", 15, (230, 255, 240), anchor="mm", bold=True)
        now = datetime.datetime.now()
        scr.text((1010, y0 + 15), now.strftime("%H:%M:%S"), 21, C_TEXT, bold=True, anchor="ra")
        scr.text((1010, y0 + 35), now.strftime("%Y-%m-%d"), 14, C_TEXT_DIM, anchor="ra")

    def mem_str(self):
        try:
            m = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                m[k] = int(v.strip().split()[0])
            used = (m["MemTotal"] - m["MemAvailable"]) // 1024
            return "RAM %dM" % used
        except Exception:
            return "RAM -"

    def draw_menu(self):
        scr = self.scr
        r = self.menu_rect()
        scr.rrect(r, 14, fill=C_MENU_BG, outline=C_LINE, width=2)
        scr.rrect([r[0] + 6, r[1] + 6, r[2] - 6, r[1] + 44], 10, fill=C_MENU_HD)
        scr.text((r[0] + 20, r[1] + 25), "应用程序", 20, (200, 220, 255), cn=True, anchor="lm")
        y = r[1] + 52
        for rr, a in self.menu_cells():
            scr.rrect(rr, 8, fill=(30, 40, 70))
            a["icon"](scr.d, rr[0] + 10, rr[1] + 6, 30)
            scr.text((rr[0] + 52, rr[1] + 21), a["name"], 20, C_TEXT, cn=True, anchor="lm")

    def menu_items(self):
        return self.menu_cells()

    # ---- 应用 ----
    def run_app(self, a):
        scr = self.scr
        self.draw(pressed=a["name"])          # 按下反馈
        time.sleep(0.12)
        scr.clear((0, 0, 0))
        scr.text((512, 300), "正在打开 " + a["name"], 28, (200, 220, 255), cn=True, anchor="mm")
        scr.flush()
        time.sleep(0.25)
        try:
            import importlib
            mod = __import__(a["mod"])
            # 每次都重新加载, 这样改了应用代码不用重启桌面就生效
            try:
                mod = importlib.reload(mod)
            except Exception:
                pass
            # ★ 全局"回桌面"保险：跑应用期间，点左上角那块都会抛 ExitApp。
            #   这样**任何**应用（包括以后新写的）都一定能退出来，
            #   不会再出现"进得去出不来"。
            self.touch.exit_zone = EXIT_ZONE
            try:
                mod.run(scr, self.touch)
            finally:
                self.touch.exit_zone = None
        except fbui.ExitApp:
            print("[app] 左上角返回 -> 回桌面:", a["name"])
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print("APP ERROR:", tb)
            scr.clear((60, 0, 0))
            scr.text((30, 26), "应用出错: " + a["name"], 26, (255, 200, 200), cn=True)
            yy = 76
            for line in tb.strip().split("\n")[-8:]:
                scr.text((30, yy), line[:80], 16, (255, 220, 220), mono=True)
                yy += 22
            scr.text((512, 560), "点屏幕返回桌面", 24, (255, 255, 255), cn=True, anchor="mm")
            scr.flush()
            while True:
                if self.touch.poll():
                    break
                time.sleep(0.05)
        self.draw()

    def _beat(self):
        """写心跳文件。

        ★ 为什么需要：zynq-screen-guard 只会救【黑屏】，救不了【画面冻结】——
          主循环若被某个阻塞调用卡住，画面停在最后一帧，看着正常但点哪都没反应。
          `/usr/local/bin/desktop-watchdog.sh` 定时检查这个文件，超时就重启桌面。
        """
        try:
            with open("/run/desktop_beat", "w") as f:
                f.write("%.3f" % time.time())
        except Exception:
            pass

    def tick(self):
        """每秒刷新状态栏 + 检查壁纸有没有被换掉"""
        now = datetime.datetime.now()
        t = now.strftime("%H:%M:%S")
        if t != self.last_clock:
            self.last_clock = t
            self._beat()                        # ★ 心跳: 给卡死看门狗用
            if time.time() - self.last_cpu_t > 1.0:
                self.cpu = self.read_cpu()
                self.last_cpu_t = time.time()
            H = getattr(self, "home", None)
            if H is not None:
                if self.at_home:
                    self.redraw_home()          # 首页: 只重画变化的小方框
                else:
                    # 图标页: 只有顶部状态栏那一行需要刷新（别调 draw_taskbar,
                    # 否则旧任务栏会盖在新 Dock 上）
                    scr = self.scr
                    scr.d.rectangle([0, 0, 1024, 29], fill=(12, 17, 30))
                    scr.d.line([(0, 29), (1024, 29)], fill=(40, 52, 78))
                    H.page = 1 + self.page
                    H.n_pages = self.total_pages()
                    H.draw_status()
                    scr.flush([0, 0, 1024, 30])
            else:
                self.draw_taskbar()
                self.scr.flush([600 - TB_H - 2, 0, 1024, 600])
        # 壁纸被换掉了? (壁纸软件改 ~/.wallpaper 后立刻生效)
        st = self.wall_stamp()
        if st != self._wall_stamp:
            self._wall_stamp = st
            print("壁纸已切换:", open(self.WALL_CONF).read().strip()
                  if os.path.exists(self.WALL_CONF) else "(内置)")
            self.wall = self.load_wallpaper()
            self.draw()

    def read_cpu(self):
        try:
            v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
            idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
            if self._cpu_prev:
                dt, di = total - self._cpu_prev[0], idle - self._cpu_prev[1]
                self._cpu_prev = (total, idle)
                return 0 if dt <= 0 else max(0, min(100, int(100 * (dt - di) / dt)))
            self._cpu_prev = (total, idle)
        except Exception:
            pass
        return self.cpu

    def launch_anim(self, a):
        """启动动画: 图标框快速放大淡出 (~0.18s)"""
        scr = self.scr
        for i, (x0, y0, x1, y1, aa) in enumerate(self.grid()):
            if aa is not a:
                continue
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            for k in range(1, 6):
                r = int(ICON_W * 0.5 * (1 + k * 0.35))
                scr.img.paste(self.wall, (x0 - r, y0 - r))
                scr.d = ImageDraw.Draw(scr.img)
                col = (90 + k * 20, 150 + k * 15, 230)
                scr.rrect([cx - r, cy - r, cx + r, cy + r], 18, outline=col, width=3)
                scr.flush([max(0, x0 - r), max(0, y0 - r),
                           min(1024, x1 + r), min(600 - TB_H, y1 + r + 30)])
            break

    def _try_start_drag(self, x=None, y=None):
        """★ 判定是否进入"拖动"状态

        条件: 按住超过 DRAG_HOLD 秒 【并且】手指移动超过 DRAG_MOVE 像素
        为什么需要"移动"这一条:
            只按时间判定的话, 用户"慢点一下"(按住 0.4 秒)就会被当成拖动,
            图标弹起来、松手什么也没发生 -> 应用打不开, 感觉"很诡异"。
        为什么没传坐标时要用 down_xy:
            主循环里没有事件的那一帧也会调用本函数 (为了不漏掉长按),
            这时没有新坐标 —— 必须拿落笔点当"当前位置", 否则会误判成
            "已经移动" 而启动拖动, 并且 drag_pos 保持 (0,0) -> 图标飞到左上角。
        """
        if self.drag is not None or self.press_t <= 0:
            return
        if self.pressed is None or self.pressed < 0 or self.down_xy is None:
            return
        if time.time() - self.press_t < DRAG_HOLD:
            return
        if x is None:
            x, y = self.down_xy          # ★ 没有新坐标 -> 用落笔点 (位移=0)
        # 移动不够 -> 还是点击, 不是拖动
        if (abs(x - self.down_xy[0]) < DRAG_MOVE
                and abs(y - self.down_xy[1]) < DRAG_MOVE):
            return
        pg = self.pages[self.page]
        name = pg[self.pressed] if self.pressed < len(pg) else None
        byname = {a["name"]: a for a in APPS}
        if name not in byname:
            return
        self.drag = byname[name]
        self.drag_from = self.pressed
        self.drag_from_page = self.page
        self.edge_t = time.time()
        # 记住"手指抓住图标的哪个位置", 拖动时保持这个相对位置
        slots = self.grid()
        if self.pressed < len(slots):
            gx = slots[self.pressed][0] + ICON_W // 2
            gy = slots[self.pressed][1] + ICON_H // 2
            self.grab_off = (self.down_xy[0] - gx, self.down_xy[1] - gy)
        else:
            self.grab_off = (0, 0)
        self.drag_pos = (x, y)
        print("开始拖动: %s  (抓取偏移 %s)" % (self.drag["name"], self.grab_off))
        self.draw()

    def _drag_icon_center(self):
        """拖动中图标中心当前在哪 (落点判断用图标中心, 不用手指 —— 更符合直觉)"""
        dx, dy = self.drag_pos
        ox, oy = getattr(self, "grab_off", (0, 0))
        return (dx - ox, dy - oy)

    def run(self):
        self.draw()
        print("桌面 v3 已启动 (%d 页, 长按图标可拖动)" % self.page_count())
        while True:
            ev = self.touch.poll(move=True)
            if ev:
                kind, x, y = ev

                # ---------- 落笔 ----------
                if kind == "down":
                    self.press_t = time.time()
                    self.down_xy = (x, y)
                    self.pressed = self.slot_at(x, y)
                    if self.at_home:
                        self.pressed = -1     # 首页不拖图标, 但点击要生效
                    self.swipe_x = x
                    self.swipe_y = y
                    self.swipe_t = time.time()
                    continue

                # ---------- 移动中 ----------
                if kind == "move":
                    # 长按 + 移动超过阈值 -> 进入拖动
                    self._try_start_drag(x, y)

                    if self.drag is not None:
                        # 拖动中: 跟踪手指 (保持抓取偏移), 只刷图标那一小块
                        old_r = self._drag_rect()
                        self.drag_pos = (x, y)
                        new_r = self._drag_rect()
                        dirty = [min(old_r[0], new_r[0]), min(old_r[1], new_r[1]),
                                 max(old_r[2], new_r[2]), max(old_r[3], new_r[3])]
                        # ★ 拖到屏幕边缘停留一会儿 -> 自动翻页 (这样才能把图标拖到别的页)
                        can_left = self.page > 0
                        can_right = self.page < self.page_count() - 1
                        if x < EDGE_ZONE and can_left:
                            if self.edge_t <= 0:
                                self.edge_t = time.time()
                            elif time.time() - self.edge_t > EDGE_DWELL:
                                self.goto_page(self.page - 1)
                                self.edge_t = 0
                                self.draw()
                                continue
                            dirty = [0, 0, EDGE_ZONE + 60, 600]     # 把提示箭头也刷上
                        elif x > 1024 - EDGE_ZONE and can_right:
                            if self.edge_t <= 0:
                                self.edge_t = time.time()
                            elif time.time() - self.edge_t > EDGE_DWELL:
                                self.goto_page(self.page + 1)
                                self.edge_t = 0
                                self.draw()
                                continue
                            dirty = [1024 - EDGE_ZONE - 60, 0, 1024, 600]
                        else:
                            self.edge_t = 0
                        self.draw(fast=dirty)
                        continue

                    # 不是拖动: 判断左右滑动翻页
                    # 要求: 横向位移够大 + 明显比纵向大 + 动作够快 (避免误触)
                    if self.swipe_x is not None and self.pressed == -1:
                        dx = x - self.swipe_x
                        dy = y - self.swipe_y if self.swipe_y is not None else 0
                        if (abs(dx) > SWIPE_MIN and abs(dx) > abs(dy) * 2.5
                                and time.time() - self.swipe_t < 0.7):
                            if self.at_home:
                                if dx < 0:                    # 首页往左滑 -> 图标页
                                    self.at_home = False
                                    self.draw()
                            elif dx > 0 and self.page == 0:
                                self.go_home(True)            # 图标首页往右滑 -> 回卡片首页
                            else:
                                self.goto_page(self.page + (1 if dx < 0 else -1))
                            self.swipe_x = None
                            continue
                    continue

                # ---------- 抬笔 ----------
                if kind == "up":
                    if self.drag is not None:
                        # 用【图标中心】判断落在哪个格子 (用图标中心更符合直觉)
                        cx, cy = self._drag_icon_center()
                        to = self.slot_at(cx, cy)
                        print("松手: 图标中心(%d,%d) -> 第%d页 第%d格 (来自 第%d页 第%d格)"
                              % (cx, cy, self.page + 1, to,
                                 self.drag_from_page + 1, self.drag_from))
                        if to >= 0 and (to != self.drag_from
                                        or self.page != self.drag_from_page):
                            self.move_app(self.drag_from_page, self.drag_from,
                                          self.page, to)
                            print("移动: %s -> 第%d页 第%d格"
                                  % (self.drag["name"], self.page + 1, to))
                        else:
                            print("落点无效或没变, 图标回原位")
                        self.drag = None
                        self.press_t = 0.0
                        self.pressed = None
                        self.down_xy = None
                        self.draw()
                        continue
                    self.press_t = 0.0
                    self.swipe_x = None
                    # 刚才是"点击"吗? (落点和抬点接近才当点击)
                    if self.pressed is not None and (self.pressed >= 0 or self.at_home):
                        self._do_tap(x, y)
                    self.pressed = None
                    continue

                # ---------- 注入的 tap ----------
                self._do_tap(x, y)
                continue

            # 没有事件也要检查: ① 长按超时 ② 拖动停在边缘的翻页计时
            self._try_start_drag()
            # ---- 边缘翻页计时 (必须在无事件帧也跑, 否则手指停着不动就永远不触发) ----
            if self.drag is not None and self.edge_t > 0:
                ex, ey = self.drag_pos
                can_left = self.page > 0
                can_right = self.page < self.page_count() - 1
                if (ex < EDGE_ZONE and can_left) or (ex > 1024 - EDGE_ZONE and can_right):
                    if time.time() - self.edge_t > EDGE_DWELL:
                        self.goto_page(self.page - 1 if ex < EDGE_ZONE else self.page + 1)
                        self.edge_t = 0
                        self.draw()
                    else:
                        # 画进度圈
                        self.draw(fast=[0, 0, 1024, 600 - TB_H])
                else:
                    self.edge_t = 0
            self.tick()
            time.sleep(0.03)

    def _do_tap(self, x, y):
        """处理一次点击 (不含拖动)"""
        H = getattr(self, "home", None)

        # ---------- 开始菜单 ----------
        if self.menu_open:
            for r, a in self.menu_items():
                if hit(r, x, y):
                    self.menu_open = False
                    self.run_app(a)
                    return
            self.menu_open = False
            if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
                self.menu_open = True
            self.draw()
            return

        # ---------- 卡片首页上的点击 ----------
        if self.at_home and H is not None:
            act = H.hit(x, y)
            if not act:
                return
            kind, v = act
            if kind == "dock":
                self.dock_action(v)
            elif kind == "menu":
                self.menu_open = True
                self.draw()
            elif kind == "page":
                if v == 0:
                    self.go_home(True)
                else:
                    self.at_home = False
                    self.goto_page(v - 1)
            elif kind == "card":
                self.card_action(v)
            elif kind == "app":
                print("[recent] 打开:", v)
                a = self.by_name(v)
                if a:
                    self.launch_anim(a)
                    self.run_app(a)
            return

        # ---------- 图标页: 只认 Dock / 全部应用按钮 / 页码点 ----------
        # ★ 这里**故意不认** ("card", ...)：
        #   首页那 6 张卡片的矩形加起来几乎盖满整个 1024x600，
        #   而图标页的 12 个图标正好落在这片区域里。原来这里遇到
        #   ("card",…) 就 return，结果 12 个图标**全部点不动** ——
        #   这就是"点不进去软件"。卡片只是首页的"幽灵矩形"，图标页上不该管它。
        if H is not None:
            act = H.hit(x, y)
            if act:
                kind, v = act
                if kind == "dock":
                    self.dock_action(v)
                    return
                if kind == "menu":
                    self.menu_open = True
                    self.draw()
                    return
                if kind == "page":
                    if v == 0:
                        self.go_home(True)
                    else:
                        self.goto_page(v - 1)
                    return
                # "card" / "app" 都不理会，往下按图标格处理

        # ---------- 旧任务栏的"开始"按钮 (只在菜单锚定时才画出来) ----------
        if hit([12, 600 - TB_H + 10, 116, 600 - 10], x, y):
            self.menu_open = True
            self.draw()
            return
        # 底部页码点
        n = self.page_count()
        if n > 1:
            gap = 22
            x0 = (1024 - n * gap) // 2 + gap // 2
            ydot = 600 - TB_H - 22
            if abs(y - ydot) < 22:
                i = int(round((x - x0) / float(gap)))
                if 0 <= i < n:
                    self.goto_page(i)
                    return
        # 图标
        is_last = (self.page == self.page_count() - 1)
        for i, (x0, y0, x1, y1, a) in enumerate(self.grid()):
            if x0 <= x <= x1 and y0 <= y <= y1:
                if a is None:
                    free = self._free_slots()
                    if is_last and free and i == free[-1]:
                        self.add_page()
                    return
                print("打开:", a["name"])
                self.launch_anim(a)
                self.run_app(a)
                return


if __name__ == "__main__":
    # 兜底: 桌面是"电器", 不能因为一个偶发异常就整块黑掉。
    # 连续 3 次都起不来才放弃, 交给 systemd / 黑屏守护去处理。
    _fails = 0
    while _fails < 3:
        try:
            Desktop().run()
            break
        except KeyboardInterrupt:
            break
        except Exception:
            import traceback
            traceback.print_exc()
            _fails += 1
            print("桌面异常退出 (第 %d 次), 2 秒后重来" % _fails)
            time.sleep(2)
    else:
        raise SystemExit("桌面连续出错 3 次, 交给 systemd / 黑屏守护")
