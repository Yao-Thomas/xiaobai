#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_fight.py —— 死神VS火影 风格 2D 格斗游戏（板子原生 / 触屏操作）

为什么这个能跑而 3D 跑不动:
    2D 格斗 = 几十个精灵贴图, 每帧只是"贴图 + 矩形拷贝"。
    而 3D 要处理几十万个三角形的顶点变换 + 深度测试 + 透视纹理映射。
    实测: 本机 framebuffer 全屏刷新 33ms (30FPS), 局部刷新只要几毫秒。

技术要点:
    * 背景/角色各动作帧/UI 全部【预渲染】成 PIL Image, 每帧只做 paste
    * 每帧只 flush【双方角色的包围盒】, 不推整屏  -> ~30-60 FPS
    * HUD 只在血量/气量/计时变化时推
    * 触摸: 左下十字方向键 + 右下 4 个动作键

操作:
    ← →  移动      ↑ 跳跃      ↓ 下蹲
    轻   轻攻击(快, 伤害小)
    重   重攻击(慢, 伤害大, 击退远)
    必杀 必杀技(消耗 50 气, 发波)
    防   防御(伤害降到 20%)

玩法: 三局两胜, 每局 60 秒, 时间到血多者胜。
"""
import math
import os
import random
import time

from PIL import Image, ImageDraw

from fbui import font

W, H = 1024, 600

# ---------------- 场地参数 ----------------
GROUND_Y = 462                  # 地面线(脚底)
SKY_H = GROUND_Y
HUD_H = 78
PX0 = 74                        # 血条左端(头像右边)
PX1 = 468                       # 血条右端
HBW = PX1 - PX0                 # 血条宽度
MBW = 296                       # 气条宽度
STAGE_L = 46                    # 角色活动左边界
STAGE_R = W - 46                # 右边界

# ---------------- 角色参数 ----------------
MAX_HP = 100
MAX_MP = 100
WALK_SPD = 4.2
BACK_SPD = 3.2
JUMP_VY = -14.0
GRAVITY = 0.78
AIR_DRAG = 0.995
BODY_HW = 30                    # 身体半宽(碰撞用)
PUSH_GAP = 8                    # 两人最小间距

# ---------------- 招式表 ----------------
# total  总帧数
# h0,h1  攻击判定生效的帧区间
# dmg    伤害   stun 对方硬直帧   kb 击退速度
# mp     消耗气   gain 命中所获气
# box    (x0,y0,x1,y1) 攻击框相对角色脚底中心的位置(朝右)
MOVES = {
    "atk_l": dict(total=16, h0=4, h1=7, dmg=6, stun=13, kb=3.0, mp=0, gain=9,
                  box=(30, -150, 112, -92), name="轻"),
    "atk_h": dict(total=26, h0=8, h1=13, dmg=14, stun=21, kb=8.5, mp=0, gain=13,
                  box=(28, -162, 148, -66), name="重"),
    "special": dict(total=42, h0=14, h1=26, dmg=22, stun=28, kb=13.0, mp=34, gain=8,
                    box=(34, -172, 210, -74), name="必杀", proj=True),
}
BLOCK_DMG = 0.2                 # 防御时伤害倍率

# ---------------- 角色配色 ----------------
CHARS = [
    dict(
        key="naruto", title="漩涡·火影", short="火影",
        hair=(255, 206, 82), hair2=(214, 152, 30),
        skin=(255, 214, 176), skin2=(226, 176, 138),
        suit=(242, 130, 44), suit2=(198, 96, 26),
        trim=(52, 104, 200), trim2=(30, 66, 140),
        band=(76, 122, 208), eye=(70, 150, 240),
        weapon=None, aura=(255, 150, 60),
    ),
    dict(
        key="ichigo", title="黑崎·死神", short="死神",
        hair=(255, 146, 56), hair2=(206, 100, 24),
        skin=(250, 222, 194), skin2=(222, 186, 154),
        suit=(34, 34, 44), suit2=(16, 16, 24),
        trim=(228, 228, 234), trim2=(170, 170, 180),
        band=None, eye=(120, 190, 255),
        weapon="sword", aura=(120, 190, 255),
    ),
]


# ==================================================================
#  小工具
# ==================================================================
def rr(d, xy, r, fill=None, outline=None, width=1):
    """圆角矩形 (PIL 7 没有 rounded_rectangle)"""
    x0, y0, x1, y1 = xy
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    if fill:
        d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
            d.ellipse([cx, cy, cx + 2 * r, cy + 2 * r], fill=fill)
    if outline and width > 0:
        for k in range(width):
            d.arc([x0 + k, y0 + k, x0 + 2 * r - k, y0 + 2 * r - k], 180, 270, fill=outline)
            d.arc([x1 - 2 * r + k, y0 + k, x1 - k, y0 + 2 * r - k], 270, 360, fill=outline)
            d.arc([x0 + k, y1 - 2 * r + k, x0 + 2 * r - k, y1 - k], 90, 180, fill=outline)
            d.arc([x1 - 2 * r + k, y1 - 2 * r + k, x1 - k, y1 - k], 0, 90, fill=outline)
            d.line([x0 + r, y0, x1 - r, y0], fill=outline, width=width)
            d.line([x0 + r, y1, x1 - r, y1], fill=outline, width=width)
            d.line([x0, y0 + r, x0, y1 - r], fill=outline, width=width)
            d.line([x1, y0 + r, x1, y1 - r], fill=outline, width=width)


def limb(d, p0, p1, w, fill, outline=None):
    """画一段肢体(带描边)"""
    if outline:
        d.line([p0, p1], fill=outline, width=w + 3)
    d.line([p0, p1], fill=fill, width=w)


def ball(d, cx, cy, r, fill, outline=None, ow=2):
    if outline:
        d.ellipse([cx - r - ow, cy - r - ow, cx + r + ow, cy + r + ow], fill=outline)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


# ==================================================================
#  角色绘制 —— 骨架 + 分节肢体 + 服装
#
#  旧版是"一个圆角矩形当躯干 + 四根棍子当手脚", 所以看着像火柴人。
#  现在按真正的骨架画: 髋/胸/肩/肘/腕/膝/踝都是独立坐标, 肢体是带锥度的
#  分节多边形(大腿-小腿 / 上臂-前臂), 再叠上服装(羽织、夹克、腰带、护额、
#  忍者鞋)和明暗两级, 才像格斗游戏里的角色。
# ==================================================================
SW, SH = 440, 300               # 精灵画布(要够宽, 否则必杀挥刀时刀尖会被裁掉)
FOOT = (170, 284)               # 画布里的脚底位置
OL = (26, 20, 26)               # 统一描边色
INK = (12, 9, 14)               # 更深的描边

# 骨架比例 (相对脚底的 y 偏移, 负数向上)
Y_ANKLE = -16
Y_KNEE = -52
Y_HIP = -86
Y_WAIST = -98
Y_CHEST = -128
Y_NECK = -144
Y_HEAD = -178
HEAD_R = 22


def _quad(p0, p1, w0, w1):
    """两端点半宽不同 -> 带锥度的四边形 (画肢体用)"""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    return [(p0[0] + nx * w0, p0[1] + ny * w0),
            (p1[0] + nx * w1, p1[1] + ny * w1),
            (p1[0] - nx * w1, p1[1] - ny * w1),
            (p0[0] - nx * w0, p0[1] - ny * w0)]


def seg(d, p0, p1, w0, w1, fill, ol=OL, ow=3):
    """一节肢体: 先画加粗的描边, 再画本体"""
    if ol and ow:
        d.polygon(_quad(p0, p1, w0 + ow, w1 + ow), fill=ol)
    d.polygon(_quad(p0, p1, w0, w1), fill=fill)


def cball(d, cx, cy, r, fill, ol=OL, ow=3):
    if ol and ow:
        d.ellipse([cx - r - ow, cy - r - ow, cx + r + ow, cy + r + ow], fill=ol)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _body(pose):
    """这个姿态下所有关节的位置 (原点 = 脚底中心, 朝向 = 右)"""
    J = {
        "foot_f": (32, Y_ANKLE), "knee_f": (28, Y_KNEE),
        "foot_b": (-30, Y_ANKLE), "knee_b": (-26, Y_KNEE),
        "hip": (0, Y_HIP), "waist": (0, Y_WAIST),
        "chest": (4, Y_CHEST), "neck": (4, Y_NECK), "head": (8, Y_HEAD),
        "sh_f": (18, Y_CHEST + 6), "elb_f": (40, Y_CHEST + 22),
        "hand_f": (50, Y_CHEST - 2),
        "sh_b": (-8, Y_CHEST + 6), "elb_b": (-28, Y_CHEST + 24),
        "hand_b": (-16, Y_CHEST + 8),
        "dy": 0.0,
    }
    if pose == "idle2":
        J["dy"] = 3
    elif pose == "walk1":
        J["foot_f"] = (36, Y_ANKLE); J["knee_f"] = (32, Y_KNEE - 5)
        J["foot_b"] = (-32, Y_ANKLE - 16); J["knee_b"] = (-26, Y_KNEE - 7)
        J["sh_f"] = (18, Y_CHEST + 2); J["hand_f"] = (52, Y_CHEST + 2)
    elif pose == "walk2":
        J["foot_f"] = (32, Y_ANKLE - 16); J["knee_f"] = (28, Y_KNEE - 7)
        J["foot_b"] = (-36, Y_ANKLE); J["knee_b"] = (-32, Y_KNEE - 5)
        J["sh_b"] = (-8, Y_CHEST + 2); J["hand_b"] = (-22, Y_CHEST + 16)
    elif pose == "jump":
        for k in ("foot_f", "knee_f", "foot_b", "knee_b", "hip", "waist",
                  "chest", "neck", "head", "sh_f", "elb_f", "hand_f",
                  "sh_b", "elb_b", "hand_b"):
            x, y = J[k]; J[k] = (x, y - 16)
        J["foot_f"] = (40, Y_ANKLE - 28); J["knee_f"] = (34, Y_KNEE - 20)
        J["foot_b"] = (-26, Y_ANKLE - 36); J["knee_b"] = (-24, Y_KNEE - 24)
        J["hand_f"] = (56, Y_CHEST - 42)
    elif pose == "crouch":
        for k in ("hip", "waist", "chest", "neck", "head", "sh_f", "elb_f",
                  "hand_f", "sh_b", "elb_b", "hand_b"):
            x, y = J[k]; J[k] = (x, y + 34)
        J["knee_f"] = (36, Y_KNEE + 14); J["knee_b"] = (-34, Y_KNEE + 14)
        J["hand_f"] = (52, Y_CHEST + 30)
    elif pose == "atk_l":
        J["chest"] = (10, Y_CHEST); J["head"] = (14, Y_HEAD)
        J["elb_f"] = (36, Y_CHEST + 6); J["hand_f"] = (92, Y_CHEST + 8)
        J["elb_b"] = (-24, Y_CHEST + 24); J["hand_b"] = (-8, Y_CHEST + 18)
        J["foot_f"] = (42, Y_ANKLE)
    elif pose == "atk_h":
        J["chest"] = (16, Y_CHEST + 2); J["head"] = (22, Y_HEAD + 2)
        J["elb_f"] = (34, Y_CHEST - 8); J["hand_f"] = (92, Y_CHEST - 28)
        J["elb_b"] = (-18, Y_CHEST + 20); J["hand_b"] = (4, Y_CHEST - 4)
        J["foot_f"] = (48, Y_ANKLE); J["knee_f"] = (44, Y_KNEE - 6)
        J["foot_b"] = (-42, Y_ANKLE - 8)
    elif pose == "special":
        J["chest"] = (8, Y_CHEST - 2); J["head"] = (12, Y_HEAD - 4)
        J["elb_f"] = (34, Y_CHEST + 2); J["hand_f"] = (84, Y_CHEST - 18)
        J["elb_b"] = (-30, Y_CHEST + 6); J["hand_b"] = (10, Y_CHEST - 12)
        J["foot_f"] = (46, Y_ANKLE); J["foot_b"] = (-42, Y_ANKLE)
    elif pose == "atk_l_w":
        # 蓄力: 拳头收到身后
        J["chest"] = (-6, Y_CHEST); J["head"] = (-2, Y_HEAD)
        J["elb_f"] = (16, Y_CHEST + 18); J["hand_f"] = (0, Y_CHEST + 10)
        J["elb_b"] = (-28, Y_CHEST + 22); J["hand_b"] = (-14, Y_CHEST + 18)
        J["foot_f"] = (30, Y_ANKLE)
    elif pose == "atk_l_r":
        # 收招: 拳头往回带
        J["chest"] = (6, Y_CHEST); J["head"] = (9, Y_HEAD)
        J["elb_f"] = (40, Y_CHEST + 14); J["hand_f"] = (58, Y_CHEST + 2)
        J["elb_b"] = (-24, Y_CHEST + 24); J["hand_b"] = (-10, Y_CHEST + 16)
    elif pose == "atk_h_w":
        J["chest"] = (-10, Y_CHEST); J["head"] = (-6, Y_HEAD - 2)
        J["elb_f"] = (20, Y_CHEST - 20); J["hand_f"] = (2, Y_CHEST - 40)
        J["elb_b"] = (-24, Y_CHEST + 16); J["hand_b"] = (-18, Y_CHEST - 6)
        J["foot_f"] = (26, Y_ANKLE); J["foot_b"] = (-38, Y_ANKLE)
    elif pose == "atk_h_r":
        J["chest"] = (10, Y_CHEST + 4); J["head"] = (14, Y_HEAD + 4)
        J["elb_f"] = (36, Y_CHEST + 6); J["hand_f"] = (66, Y_CHEST + 20)
        J["elb_b"] = (-22, Y_CHEST + 22); J["hand_b"] = (-6, Y_CHEST + 12)
        J["foot_f"] = (40, Y_ANKLE)
    elif pose == "special_w":
        J["chest"] = (-8, Y_CHEST - 4); J["head"] = (-6, Y_HEAD - 6)
        J["elb_f"] = (18, Y_CHEST - 14); J["hand_f"] = (0, Y_CHEST - 34)
        J["elb_b"] = (-28, Y_CHEST - 6); J["hand_b"] = (-16, Y_CHEST - 26)
        J["foot_f"] = (32, Y_ANKLE); J["foot_b"] = (-36, Y_ANKLE)
    elif pose == "special_r":
        J["chest"] = (10, Y_CHEST + 2); J["head"] = (13, Y_HEAD)
        J["elb_f"] = (38, Y_CHEST + 8); J["hand_f"] = (60, Y_CHEST - 2)
        J["elb_b"] = (-24, Y_CHEST + 12); J["hand_b"] = (-4, Y_CHEST + 2)
        J["foot_f"] = (40, Y_ANKLE); J["foot_b"] = (-38, Y_ANKLE)
    elif pose == "block":
        J["chest"] = (-8, Y_CHEST + 4); J["head"] = (-8, Y_HEAD + 6)
        J["elb_f"] = (16, Y_CHEST + 16); J["hand_f"] = (30, Y_CHEST - 36)
        J["elb_b"] = (-2, Y_CHEST + 14); J["hand_b"] = (22, Y_CHEST - 24)
        J["foot_f"] = (20, Y_ANKLE); J["foot_b"] = (-36, Y_ANKLE)
    elif pose == "hit":
        J["chest"] = (-18, Y_CHEST + 4); J["head"] = (-26, Y_HEAD + 8)
        J["elb_f"] = (6, Y_CHEST + 10); J["hand_f"] = (34, Y_CHEST - 22)
        J["elb_b"] = (-32, Y_CHEST + 4); J["hand_b"] = (-56, Y_CHEST - 14)
        J["foot_f"] = (30, Y_ANKLE); J["foot_b"] = (-46, Y_ANKLE - 6)
    return J


def _shoe(d, cfg, p, side):
    """忍者鞋: 脚掌 + 鞋帮"""
    x, y = p
    col = cfg["trim"] if cfg["key"] == "naruto" else (28, 28, 36)
    d.ellipse([x - 15 + 2 * side, y - 8, x + 13 + 8 * side, y + 8], fill=OL)
    d.ellipse([x - 12 + 2 * side, y - 6, x + 10 + 8 * side, y + 6], fill=col)
    if cfg["key"] == "naruto":
        d.rectangle([x - 10 + 2 * side, y - 8, x + 6 + 4 * side, y - 4],
                    fill=(238, 240, 246))


def _torso(d, cfg, P):
    """躯干 + 服装: 鸣人是橙色夹克(蓝领/蓝肩), 一护是黑色死霸装 + 白腰带"""
    sk = cfg["skin"]
    su, su2 = cfg["suit"], cfg["suit2"]
    tr, tr2 = cfg["trim"], cfg["trim2"]
    hx, hy = P["hip"]
    wx, wy = P["waist"]
    cx, cy = P["chest"]
    nx, ny = P["neck"]
    naruto = cfg["key"] == "naruto"

    # 躯干轮廓: 肩宽 -> 腰 -> 髋
    body = [(cx - 26, cy - 10), (cx + 26, cy - 10), (cx + 30, cy + 14),
            (wx + 22, wy + 6), (hx + 20, hy + 4), (hx - 20, hy + 4),
            (wx - 22, wy + 6), (cx - 30, cy + 14)]
    d.polygon([(x + 3, y + 3) for (x, y) in body], fill=OL)
    d.polygon(body, fill=su)

    if naruto:
        # 蓝色领口
        d.polygon([(cx - 22, cy - 12), (cx + 22, cy - 12), (cx + 14, cy + 10),
                   (cx - 14, cy + 10)], fill=tr)
        # 蓝色肩片
        d.polygon([(cx - 30, cy - 12), (cx - 14, cy - 12), (cx - 16, cy + 8),
                   (cx - 30, cy + 8)], fill=tr)
        # 拉链
        d.line([(cx + 2, cy - 8), (wx + 2, wy + 4)], fill=tr2, width=3)
        d.line([(cx + 2, cy - 8), (wx + 2, wy + 4)], fill=(238, 240, 246), width=1)
        # 橙色夹克的暗部
        d.polygon([(wx - 22, wy + 6), (hx - 20, hy + 4), (hx - 20, hy + 14),
                   (wx - 22, wy + 16)], fill=su2)
    else:
        # 白色内衬 V 领
        d.polygon([(cx - 10, cy - 12), (cx + 12, cy - 12), (cx + 4, cy + 12)],
                  fill=(238, 238, 244))
        d.polygon([(cx - 10, cy - 12), (cx - 2, cy + 12), (cx + 4, cy + 12)],
                  fill=tr2)
        # 交叠的前襟
        d.line([(cx + 14, cy - 10), (wx + 6, wy + 2), (hx + 2, hy)], fill=su2,
               width=4)
        # 死霸装的暗部
        d.polygon([(wx - 22, wy + 6), (hx - 20, hy + 4), (hx - 20, hy + 14),
                   (wx - 22, wy + 16)], fill=(16, 16, 22))

    # 腰带 (一护: 白色; 鸣人: 蓝色)
    belt = (240, 240, 246) if not naruto else cfg["trim2"]
    d.rectangle([hx - 21, hy - 8, hx + 21, hy + 4], fill=OL)
    d.rectangle([hx - 19, hy - 6, hx + 19, hy + 2], fill=belt)
    if not naruto:
        d.line([(hx - 4, hy - 6), (hx - 22, hy + 14)], fill=belt, width=4)


def _head(d, cfg, P, pose):
    """头 + 头发 + 侧脸五官"""
    sk, sk2 = cfg["skin"], cfg["skin2"]
    hr, hr2 = cfg["hair"], cfg["hair2"]
    naruto = cfg["key"] == "naruto"
    hx, hy = P["head"]
    nx, ny = P["neck"]

    # 脖子
    seg(d, (nx, ny + 2), (hx, hy + HEAD_R - 6), 11, 12, sk2, OL, 2)

    if naruto:
        # 金色刺猬头: 头顶一圈尖刺 + 后脑一撮
        pts = []
        for k in range(13):
            ang = math.pi * 1.02 + k * math.pi * 0.98 / 12.0
            rad = HEAD_R + 12 + (9 if k % 2 == 0 else -1)
            pts.append((hx + math.cos(ang) * rad, hy + math.sin(ang) * rad))
        pts.append((hx + HEAD_R * 0.9, hy + HEAD_R * 0.55))
        pts.append((hx + HEAD_R * 1.0, hy - HEAD_R * 0.5))
        d.polygon(pts, fill=OL)
        pts2 = []
        for k in range(13):
            ang = math.pi * 1.02 + k * math.pi * 0.98 / 12.0
            rad = HEAD_R + 9 + (7 if k % 2 == 0 else -2)
            pts2.append((hx + math.cos(ang) * rad, hy + math.sin(ang) * rad))
        pts2.append((hx + HEAD_R * 0.85, hy + HEAD_R * 0.5))
        pts2.append((hx + HEAD_R * 0.95, hy - HEAD_R * 0.5))
        d.polygon(pts2, fill=hr)
        # 后脑翘起的几撮
        for (ox, oy, w, h) in ((-30, -18, 20, 9), (-34, -4, 24, 9), (-30, 10, 18, 8)):
            d.polygon([(hx + ox, hy + oy), (hx + ox - w, hy + oy - h),
                       (hx + ox - w - 6, hy + oy + h)], fill=hr2)
        # 护额
        d.rectangle([hx - HEAD_R - 4, hy - HEAD_R + 1, hx + HEAD_R - 2,
                     hy - HEAD_R + 16], fill=OL)
        d.rectangle([hx - HEAD_R - 2, hy - HEAD_R + 3, hx + HEAD_R - 4,
                     hy - HEAD_R + 14], fill=cfg["band"])
        d.rectangle([hx - 8, hy - HEAD_R + 4, hx + 12, hy - HEAD_R + 13],
                    fill=(206, 212, 222), outline=OL)
        d.line([(hx, hy - HEAD_R + 5), (hx, hy - HEAD_R + 12)],
               fill=(120, 128, 140), width=2)
    else:
        # 橙色短发: 往上竖的尖
        d.polygon([(hx - HEAD_R - 3, hy + 6), (hx - HEAD_R - 2, hy - HEAD_R + 4),
                   (hx - 14, hy - HEAD_R - 14), (hx - 2, hy - HEAD_R - 2),
                   (hx + 8, hy - HEAD_R - 16), (hx + 16, hy - HEAD_R - 1),
                   (hx + HEAD_R + 1, hy - HEAD_R + 2), (hx + HEAD_R + 2, hy + 5)],
                  fill=hr)
        d.polygon([(hx - HEAD_R - 3, hy + 6), (hx - HEAD_R - 2, hy - HEAD_R + 4),
                   (hx - 14, hy - HEAD_R - 14), (hx - 2, hy - HEAD_R - 2),
                   (hx + 8, hy - HEAD_R - 16), (hx + 16, hy - HEAD_R - 1),
                   (hx + HEAD_R + 1, hy - HEAD_R + 2), (hx + HEAD_R + 2, hy + 5)],
                  outline=OL)
        # 刘海压到额头
        d.polygon([(hx - HEAD_R + 2, hy - HEAD_R + 6), (hx - 8, hy - HEAD_R - 8),
                   (hx + 4, hy - HEAD_R + 2), (hx + 14, hy - HEAD_R - 6),
                   (hx + HEAD_R - 1, hy - HEAD_R + 8)], fill=hr2)

    # 脸
    cball(d, hx, hy, HEAD_R, sk, OL, 3)
    # ★ 刘海只盖到额头上沿(hy-12)。以前画到 hy-2, 正好把眼睛糊掉了
    if naruto:
        d.polygon([(hx - HEAD_R - 1, hy - 13), (hx - HEAD_R + 2, hy - HEAD_R + 6),
                   (hx + HEAD_R - 2, hy - HEAD_R + 4), (hx + HEAD_R + 1, hy - 11)],
                  fill=hr)
    else:
        d.polygon([(hx - HEAD_R - 1, hy - 12), (hx - HEAD_R + 2, hy - HEAD_R + 5),
                   (hx + HEAD_R - 2, hy - HEAD_R + 3), (hx + HEAD_R + 1, hy - 10)],
                  fill=hr)
        # 一护标志性的几缕前发(垂到眉间)
        for (ox, w) in ((-12, 7), (2, 8), (15, 6)):
            d.polygon([(hx + ox, hy - HEAD_R + 6), (hx + ox + w, hy - HEAD_R + 8),
                       (hx + ox + w // 2, hy - 6)], fill=hr)
    # 眼睛 (侧脸: 只画一只, 靠前)
    ex = hx + HEAD_R * 0.30
    ey = hy - 4
    angry = (pose in ("atk_h", "special", "hit"))
    d.polygon([(ex - 9, ey - 5), (ex + 9, ey - 7), (ex + 9, ey + 7), (ex - 9, ey + 6)],
              fill=(252, 252, 255), outline=OL)
    d.ellipse([ex - 1, ey - 5, ex + 8, ey + 5], fill=cfg["eye"])
    d.ellipse([ex + 1, ey - 3, ex + 6, ey + 3], fill=(18, 14, 20))
    d.ellipse([ex + 2, ey - 3, ex + 4, ey], fill=(255, 255, 255))
    # 眉毛 (攻击时压低)
    if angry:
        d.line([(ex - 11, ey - 10), (ex + 10, ey - 4)], fill=(70, 40, 24), width=4)
    else:
        d.line([(ex - 11, ey - 8), (ex + 10, ey - 10)], fill=(70, 40, 24), width=4)
    # 鼻子 / 嘴
    d.line([(hx + HEAD_R - 2, hy + 5), (hx + HEAD_R + 6, hy + 8)], fill=sk2, width=3)
    if pose in ("atk_h", "special"):
        d.polygon([(hx + 8, hy + 15), (hx + 22, hy + 12), (hx + 22, hy + 19),
                   (hx + 8, hy + 20)], fill=(150, 62, 62), outline=OL)
    else:
        d.line([(hx + 8, hy + 17), (hx + 21, hy + 16)], fill=(150, 80, 74), width=3)
    # 鸣人的胡须
    if naruto:
        for k in range(3):
            d.line([(hx + 12, hy + 1 + k * 6), (hx + 25, hy - 2 + k * 6)],
                   fill=(198, 146, 116), width=2)


def _sword(d, P, pose):
    """斩月: 一把大菜刀, 攻击时挥出去, 平时扛在身后"""
    # ★ 认整族名字: atk_l / atk_l_w / atk_l_r 都算"轻攻击"
    if pose.startswith("atk_l"):
        fam, swing = "l", {"atk_l_w": (-48, -54), "atk_l": (62, 34),
                           "atk_l_r": (26, 22)}.get(pose, (62, 34))
    elif pose.startswith("atk_h"):
        fam, swing = "h", {"atk_h_w": (-34, -86), "atk_h": (96, 40),
                           "atk_h_r": (46, 48)}.get(pose, (96, 40))
    elif pose.startswith("special"):
        fam, swing = "s", {"special_w": (-24, -116), "special": (150, -90),
                           "special_r": (68, -34)}.get(pose, (150, -90))
    else:
        fam, swing = "idle", None
    if fam == "idle":
        hx, hy = P["hand_b"]
        a = (hx - 6, hy - 6); b = (hx - 30, hy - 78)
    else:
        hx, hy = P["hand_f"]
        a = (hx - 10, hy + 6)
        b = (a[0] + swing[0], a[1] + swing[1])
    # 刀柄
    hx2 = a[0] - (b[0] - a[0]) * 0.16
    hy2 = a[1] - (b[1] - a[1]) * 0.16
    d.line([(hx2, hy2), a], fill=INK, width=12)
    d.line([(hx2, hy2), a], fill=(206, 208, 216), width=8)
    for k in range(4):
        t = k / 4.0
        px = hx2 + (a[0] - hx2) * t
        py = hy2 + (a[1] - hy2) * t
        d.line([(px - 5, py - 4), (px + 5, py + 4)], fill=(150, 152, 160), width=2)
    # 刀身
    dx = b[0] - a[0]; dy = b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    blade = [(a[0] + nx * 7, a[1] + ny * 7), (b[0] + nx * 11, b[1] + ny * 11),
             (b[0] - nx * 2, b[1] - ny * 2), (a[0] - nx * 5, a[1] - ny * 5)]
    d.polygon(blade, fill=INK)
    d.polygon([(x, y) for (x, y) in blade], fill=(226, 232, 240))
    d.line([(a[0] + nx * 4, a[1] + ny * 4), (b[0] + nx * 7, b[1] + ny * 7)],
           fill=(255, 255, 255), width=3)
    d.line([(a[0] - nx * 3, a[1] - ny * 3), (b[0] - nx * 1, b[1] - ny * 1)],
           fill=(140, 150, 168), width=2)


def _draw_down(cfg, d, fx, fy):
    """倒地: 整个人横躺"""
    img_d = d
    cy = fy - 34
    su, su2 = cfg["suit"], cfg["suit2"]
    sk = cfg["skin"]
    hr = cfg["hair"]
    # 腿
    seg(img_d, (fx - 74, cy + 10), (fx - 20, cy + 2), 12, 14, su2, OL, 3)
    seg(img_d, (fx - 70, cy + 26), (fx - 18, cy + 14), 12, 14, su2, OL, 3)
    # 躯干
    d.polygon([(x + 3, y + 3) for (x, y) in
               [(fx - 30, cy - 20), (fx + 30, cy - 22), (fx + 34, cy + 24),
                (fx - 28, cy + 26)]], fill=OL)
    d.polygon([(fx - 30, cy - 20), (fx + 30, cy - 22), (fx + 34, cy + 24),
               (fx - 28, cy + 26)], fill=su)
    # 手臂
    seg(img_d, (fx + 6, cy - 16), (fx - 26, cy - 44), 10, 8, su, OL, 3)
    seg(img_d, (fx - 6, cy + 6), (fx - 40, cy + 30), 10, 8, su, OL, 3)
    # 头
    hx, hy = fx + 54, cy - 6
    cball(img_d, hx, hy, HEAD_R, sk, OL, 3)
    d.polygon([(hx - HEAD_R - 2, hy + 4), (hx - 6, hy - HEAD_R - 14),
               (hx + 14, hy - HEAD_R - 4), (hx + HEAD_R + 2, hy + 2)],
              fill=hr, outline=OL)
    d.line([(hx + 8, hy - 2), (hx + 20, hy - 6)], fill=(90, 90, 96), width=3)
    d.line([(hx + 6, hy + 10), (hx + 20, hy + 10)], fill=(140, 80, 74), width=3)


def draw_pose(cfg, pose, bob=0):
    """把角色某个姿态画到 RGBA 画布上 (脚底对齐 FOOT)"""
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fx, fy = FOOT
    fy += bob
    if pose == "down":
        _draw_down(cfg, d, fx, fy)
        return img

    J = _body(pose)
    dy = J.pop("dy")
    P = dict((k, (fx + v[0], fy + v[1] + dy)) for k, v in J.items())

    sk, sk2 = cfg["skin"], cfg["skin2"]
    su, su2 = cfg["suit"], cfg["suit2"]
    dark = su2 if cfg["key"] == "naruto" else (14, 14, 20)

    # 后腿
    seg(d, P["hip"], P["knee_b"], 13, 10, dark)
    seg(d, P["knee_b"], P["foot_b"], 10, 8, dark)
    _shoe(d, cfg, P["foot_b"], -1)
    # 后臂
    seg(d, P["sh_b"], P["elb_b"], 11, 9, su2)
    seg(d, P["elb_b"], P["hand_b"], 9, 8, sk2)
    cball(d, P["hand_b"][0], P["hand_b"][1], 9, sk2, OL, 2)
    # ★ 武器: 非攻击姿态画在【身后】, 否则斩月会穿过身体
    atk = pose.startswith(("atk_", "special"))
    if cfg.get("weapon") == "sword" and not atk:
        _sword(d, P, pose)
    # 躯干 + 服装
    _torso(d, cfg, P)
    # 前腿
    seg(d, P["hip"], P["knee_f"], 14, 11, su)
    seg(d, P["knee_f"], P["foot_f"], 11, 9, su)
    _shoe(d, cfg, P["foot_f"], 1)
    # 前臂
    seg(d, P["sh_f"], P["elb_f"], 12, 10, su)
    seg(d, P["elb_f"], P["hand_f"], 10, 8, sk)
    cball(d, P["hand_f"][0], P["hand_f"][1], 10, sk, OL, 2)
    # 武器(攻击姿态画在身前)
    if cfg.get("weapon") == "sword" and atk:
        _sword(d, P, pose)
    # 头
    _head(d, cfg, P, pose)
    return img


def build_frames(ci):
    """预渲染一个角色的所有动作帧

    ★ 同时把每一帧【实际画到的范围】也切出来。精灵画布 440x300 是给刀尖
      留的余量, 每帧整块贴图 + 整块刷脏区太浪费 —— 只按真实范围来。
    """
    cfg = CHARS[ci]
    poses = ["idle", "idle2", "walk1", "walk2", "jump", "crouch",
             "atk_l", "atk_h", "special", "block", "hit", "down",
             "atk_l_w", "atk_l_r", "atk_h_w", "atk_h_r",
             "special_w", "special_r"]
    out = {}
    for p in poses:
        base = draw_pose(cfg, p)
        bb = base.getbbox() or (0, 0, SW, SH)
        out[p] = base.crop(bb)
        out[p + "_o"] = bb
        # 镜像后内容会水平翻过去, 裁剪框也要跟着翻
        mb = (SW - bb[2], bb[1], SW - bb[0], bb[3])
        out[p + "_m"] = base.transpose(Image.FLIP_LEFT_RIGHT).crop(mb)
        out[p + "_m_o"] = mb
    return out


# ==================================================================
#  背景 / 特效
# ==================================================================
def make_bg():
    """预渲染战斗背景 (黄昏 + 远山 + 月亮 + 地面)"""
    img = Image.new("RGB", (W, H), (20, 24, 48))
    d = ImageDraw.Draw(img)
    # 天空渐变
    top, bot = (38, 44, 96), (232, 138, 96)
    for y in range(SKY_H):
        t = (y / float(SKY_H)) ** 1.35
        c = (int(top[0] + (bot[0] - top[0]) * t),
             int(top[1] + (bot[1] - top[1]) * t),
             int(top[2] + (bot[2] - top[2]) * t))
        d.line([(0, y), (W, y)], fill=c)
    # 月亮
    d.ellipse([770, 54, 890, 174], fill=(255, 246, 214))
    d.ellipse([770, 54, 890, 174], outline=(255, 226, 170), width=6)
    for (cx, cy, r) in ((806, 96, 9), (846, 126, 13), (822, 146, 7)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(242, 226, 190))
    # 星星
    random.seed(7)
    for _ in range(90):
        x, y = random.randint(0, W), random.randint(0, 260)
        g = random.randint(180, 255)
        d.point((x, y), fill=(g, g, g))
    # 远山两层
    for (base, col, amp, off) in ((330, (86, 70, 110), 70, 0), (390, (58, 48, 82), 52, 180)):
        pts = [(0, H)]
        for x in range(0, W + 40, 40):
            y = base - int(amp * (0.5 + 0.5 * math.sin((x + off) / 150.0)) *
                           (0.6 + 0.4 * math.sin((x + off) / 61.0)))
            pts.append((x, y))
        pts.append((W, H))
        d.polygon(pts, fill=col)
    # 地面
    d.rectangle([0, GROUND_Y, W, H], fill=(64, 46, 40))
    for y in range(GROUND_Y, H, 12):
        c = 74 - (y - GROUND_Y) // 6
        d.line([(0, y), (W, y)], fill=(max(30, c), max(22, c - 12), max(18, c - 16)))
    d.line([(0, GROUND_Y), (W, GROUND_Y)], fill=(150, 120, 96), width=3)
    # 地面纹理
    random.seed(11)
    for _ in range(320):
        x = random.randint(0, W)
        y = random.randint(GROUND_Y + 6, H - 4)
        w = random.randint(6, 26)
        g = random.randint(-14, 14)
        d.line([(x, y), (x + w, y)], fill=(64 + g, 46 + g, 40 + g))
    return img


def make_spark(r, col):
    im = Image.new("RGBA", (r * 2, r * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k in range(9):
        a = k * math.pi / 4.5
        L = r if k % 2 == 0 else r * 0.5
        d.polygon([(r + math.cos(a) * L, r + math.sin(a) * L),
                   (r + math.cos(a + 0.5) * L * 0.3, r + math.sin(a + 0.5) * L * 0.3),
                   (r + math.cos(a - 0.5) * L * 0.3, r + math.sin(a - 0.5) * L * 0.3)],
                  fill=col)
    d.ellipse([r * 0.45, r * 0.45, r * 1.55, r * 1.55], fill=(255, 255, 255, 230))
    return im


def make_portrait(cfg, size=58):
    """HUD 用的角色头像 (原版左右各有一个圆形头像框)"""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    au = cfg["aura"]
    # 外圈(角色主题色) + 底板
    d.ellipse([0, 0, size - 1, size - 1], fill=au)
    d.ellipse([3, 3, size - 4, size - 4], fill=(24, 26, 42))
    cx, cy = size // 2, size // 2 + 4
    r = 15
    # 脖子
    d.rectangle([cx - 7, cy + 8, cx + 7, cy + 20], fill=cfg["skin2"])
    # 脸
    cball(d, cx, cy, r, cfg["skin"], (26, 20, 26), 2)
    hr, hr2 = cfg["hair"], cfg["hair2"]
    if cfg["key"] == "naruto":
        # 金色尖发
        pts = [(cx - r - 3, cy + 4)]
        for k in range(9):
            ang = math.pi * 1.05 + k * math.pi * 0.9 / 8.0
            rr2 = r + 7 + (6 if k % 2 == 0 else -1)
            pts.append((cx + math.cos(ang) * rr2, cy + math.sin(ang) * rr2))
        pts.append((cx + r + 2, cy + 3))
        d.polygon(pts, fill=hr, outline=(26, 20, 26))
        # 护额
        d.rectangle([cx - r - 2, cy - r + 1, cx + r + 1, cy - r + 10],
                    fill=cfg["band"], outline=(26, 20, 26))
        d.rectangle([cx - 5, cy - r + 3, cx + 8, cy - r + 8],
                    fill=(206, 212, 222), outline=(26, 20, 26))
        # 胡须
        for k in range(3):
            d.line([(cx + 6, cy + 1 + k * 4), (cx + 14, cy - 1 + k * 4)],
                   fill=(198, 146, 116), width=1)
    else:
        # 橙色短发
        d.polygon([(cx - r - 3, cy + 3), (cx - r - 2, cy - r + 2),
                   (cx - 8, cy - r - 8), (cx, cy - r - 1),
                   (cx + 7, cy - r - 9), (cx + 12, cy - r),
                   (cx + r + 2, cy - r + 2), (cx + r + 2, cy + 3)],
                  fill=hr, outline=(26, 20, 26))
        d.polygon([(cx - r, cy - 4), (cx - 3, cy - r - 4), (cx + 6, cy - r + 1),
                   (cx + r, cy - 5)], fill=hr2)
    # 眼睛
    for ex in (cx - 6, cx + 6):
        d.ellipse([ex - 4, cy - 4, ex + 4, cy + 5], fill=(252, 252, 255),
                  outline=(26, 20, 26))
        d.ellipse([ex - 1, cy - 2, ex + 4, cy + 4], fill=cfg["eye"])
        d.ellipse([ex, cy - 1, ex + 2, cy + 1], fill=(18, 14, 20))
    d.line([(cx - 6, cy - 8), (cx + 7, cy - 9)], fill=(70, 40, 24), width=2)
    d.line([(cx - 6, cy - 8), (cx + 7, cy - 9)], fill=(70, 40, 24), width=2)
    d.line([(cx - 5, cy + 9), (cx + 6, cy + 9)], fill=(150, 80, 74), width=2)
    return im


# ==================================================================
#  战斗者
# ==================================================================
class Fighter:
    def __init__(self, idx, frames, x, face, name):
        self.idx = idx
        self.frames = frames
        self.name = name
        self.reset(x, face)

    def reset(self, x, face):
        self.x = float(x)
        self.y = 0.0                # 离地高度(向上为正)
        self.vy = 0.0
        self.face = face            # 1 朝右, -1 朝左
        self.hp = MAX_HP
        self.mp = 0.0
        self.pose = "idle"
        self.t = 0                  # 当前动作剩余帧
        self.move = None            # 当前招式中
        self.hit_done = False       # 本次攻击是否已命中
        self.stun = 0               # 受击硬直
        self.blocking = False
        self.on_ground = True
        self.anim = 0
        self.win_pose = False
        self.flash = 0              # 受击白闪
        self.combo_hit = 0

    # ---- 查询 ----
    @property
    def alive(self):
        return self.hp > 0

    def bbox(self):
        """用于脏矩形: 角色真正会画到的屏幕范围

        ★ 必须覆盖精灵真实画到的部分(用预存的裁剪原点算), 否则上一帧的
          残留会变成拖影; 但也不能整块 440x300 都算上, 那会白白多刷一倍面积。
        """
        key = self.pose if self.pose in self.frames else "idle"
        if self.face < 0 and (key + "_m_o") in self.frames:
            key = key + "_m"
        o = self.frames.get(key + "_o", (170, 84, 170 + 100, 300))
        cx = int(self.x)
        by = int(GROUND_Y - self.y)          # ★ 必须取整: flush 要的是整数范围
        x0 = cx - FOOT[0] + int(o[0])
        y0 = by - FOOT[1] + int(o[1])
        x1 = cx - FOOT[0] + int(o[2])
        y1 = by - FOOT[1] + int(o[3])
        return (x0 - 4, y0 - 4, x1 + 6, y1 + 8)

    def hurt_box(self):
        """受击框(世界坐标)"""
        cx = int(self.x)
        return (cx - BODY_HW, GROUND_Y - self.y - 178, cx + BODY_HW, GROUND_Y - self.y)

    def attack_box(self):
        """当前攻击判定框; 没在有效帧就返回 None"""
        if not self.move:
            return None
        m = MOVES[self.move]
        cur = m["total"] - self.t
        if not (m["h0"] <= cur <= m["h1"]):
            return None
        x0, y0, x1, y1 = m["box"]
        cx = int(self.x)
        base = GROUND_Y - self.y
        if self.face > 0:
            return (cx + x0, base + y0, cx + x1, base + y1)
        return (cx - x1, base + y0, cx - x0, base + y1)

    def center(self):
        return (int(self.x), int(GROUND_Y - self.y - 56))

    # ---- 动作 ----
    def can_act(self):
        return self.stun <= 0 and (self.move is None or self.t <= 0) and self.hp > 0

    def do_move(self, key):
        if not self.can_act() or not self.on_ground:
            return False
        m = MOVES[key]
        if m["mp"] > self.mp:
            return False
        self.mp -= m["mp"]
        self.move = key
        self.t = m["total"]
        self.hit_done = False
        self.pose = key
        if key == "special":
            self.anim = 0
        return True

    def jump(self):
        if self.can_act() and self.on_ground:
            self.vy = JUMP_VY
            self.on_ground = False
            self.pose = "jump"

    def take_hit(self, dmg, kb, stun, from_dir, blocked):
        if blocked:
            self.hp = max(0, self.hp - dmg * BLOCK_DMG)
            self.stun = max(self.stun, int(stun * 0.4))
            self.x += from_dir * kb * 0.25
            self.mp = min(MAX_MP, self.mp + 3)
        else:
            self.hp = max(0, self.hp - dmg)
            self.stun = max(self.stun, stun)
            self.vy = max(self.vy, 3.0) if not self.on_ground else self.vy
            self.x += from_dir * kb
            self.mp = min(MAX_MP, self.mp + dmg * 0.6)
            self.flash = 5
            self.pose = "hit"
            self.move = None
            self.t = 0
        self.x = max(STAGE_L, min(STAGE_R, self.x))

    # ---- 每帧更新 ----
    def update(self, keys, foe, spawn_proj):
        self.anim += 1
        if self.flash > 0:
            self.flash -= 1

        # 硬直
        if self.stun > 0:
            self.stun -= 1
            self.blocking = False
        # 招式推进
        if self.move is not None:
            self.t -= 1
            m = MOVES[self.move]
            cur = m["total"] - self.t
            # ★ 三段式出招动画: 蓄力 -> 出招(判定帧) -> 收招。
            #   以前整个过程只有一个静止姿势, 看着很僵。
            if cur < m["h0"]:
                self.pose = self.move + "_w"
            elif cur <= m["h1"] + 2:
                self.pose = self.move
            else:
                self.pose = self.move + "_r"
            # 必杀发波
            if m.get("proj") and cur == m["h0"] and not self.hit_done:
                self.hit_done = True
                cx, cy = self.center()
                spawn_proj(self, cx + self.face * 60, cy + 4,
                           self.face, m["dmg"], m["stun"], m["kb"], self.idx)
            if self.t <= 0:
                self.move = None
                self.pose = "idle"
        # 物理
        self.y += self.vy
        if self.y > 0:
            self.vy -= GRAVITY
        if self.y <= 0:
            self.y = 0
            if not self.on_ground:
                self.on_ground = True
                self.pose = "idle"
            self.vy = 0
        else:
            self.on_ground = False

        # 输入 / AI 决策
        if self.can_act() and self.on_ground:
            self.blocking = keys.get("block", False)
            if self.blocking:
                self.pose = "block"
            elif keys.get("l"):
                self.do_move("atk_l")
            elif keys.get("h"):
                self.do_move("atk_h")
            elif keys.get("s"):
                self.do_move("special")
            elif keys.get("up"):
                self.jump()
            elif keys.get("left"):
                self.face = -1
                self.x -= BACK_SPD if foe.x < self.x else WALK_SPD
                self.pose = "walk1" if (self.anim // 6) % 2 == 0 else "walk2"
            elif keys.get("right"):
                self.face = 1
                self.x += WALK_SPD if foe.x > self.x else BACK_SPD
                self.pose = "walk1" if (self.anim // 6) % 2 == 0 else "walk2"
            elif keys.get("down"):
                self.pose = "crouch"
            else:
                if self.on_ground and self.move is None:
                    self.pose = "idle" if (self.anim // 22) % 2 == 0 else "idle2"

        # 空中保持跳跃姿态
        if not self.on_ground and self.move is None:
            self.pose = "jump"
        # 面向对手
        if self.on_ground and self.move is None and self.stun <= 0:
            self.face = 1 if foe.x >= self.x else -1
        # 边界
        self.x = max(STAGE_L, min(STAGE_R, self.x))
        # 死亡
        if self.hp <= 0:
            self.pose = "down"
            self.stun = max(self.stun, 2)

    def draw(self, scr):
        key = self.pose
        if key not in self.frames:
            key = "idle"
        if self.face < 0 and (key + "_m") in self.frames:
            key = key + "_m"
        img = self.frames[key]
        o = self.frames.get(key + "_o", (0, 0, SW, SH))
        cx, by = int(self.x), int(GROUND_Y - self.y)
        # ★ 精灵已经按真实内容裁剪过, 贴图原点要加上裁剪偏移
        px = cx - FOOT[0] + o[0]
        py = by - FOOT[1] + o[1]
        # 影子
        if self.on_ground:
            sw = int(40 - min(20, self.y * 0.12))
            scr.d.ellipse([cx - sw, GROUND_Y - 8, cx + sw, GROUND_Y + 10],
                          fill=(40, 28, 24))
        scr.img.paste(img, (px, py), img)
        if self.flash > 0:
            m = img.split()[3].point(lambda v: min(255, int(v * 0.55)))
            white = Image.new("RGBA", img.size, (255, 255, 255, 255))
            scr.img.paste(white, (px, py), m)


# ==================================================================
#  弹道(必杀技)
# ==================================================================
class Proj:
    def __init__(self, owner, x, y, face, dmg, stun, kb, col):
        self.owner = owner
        self.x = float(x)
        self.y = float(y)
        self.face = face
        self.dmg = dmg
        self.stun = stun
        self.kb = kb
        self.col = col
        self.life = 90
        self.t = 0

    def bbox(self):
        return (int(self.x) - 52, int(self.y) - 52, int(self.x) + 52, int(self.y) + 52)

    def update(self, foe, on_hit):
        self.t += 1
        self.life -= 1
        self.x += self.face * 13.0
        if self.life <= 0 or self.x < -80 or self.x > W + 80:
            return False
        hb = foe.hurt_box()
        px0, py0, px1, py1 = self.bbox()
        if foe.idx != self.owner and foe.hp > 0 and \
           px0 < hb[2] and px1 > hb[0] and py0 < hb[3] and py1 > hb[1]:
            on_hit(foe, self)
            return False
        return True

    def draw(self, scr):
        cx, cy = int(self.x), int(self.y)
        r = 30 + int(6 * math.sin(self.t * 0.5))
        for k in range(3, 0, -1):
            rr2 = r + k * 9
            a = 60 - k * 14
            scr.d.ellipse([cx - rr2, cy - rr2 * 0.6, cx + rr2, cy + rr2 * 0.6],
                          fill=(min(255, self.col[0]), min(255, self.col[1]),
                                min(255, self.col[2])))
        scr.d.ellipse([cx - r, cy - r * 0.62, cx + r, cy + r * 0.62], fill=(255, 255, 255))
        scr.d.ellipse([cx - r * 0.6, cy - r * 0.36, cx + r * 0.6, cy + r * 0.36],
                      fill=self.col)


# ==================================================================
#  AI
# ==================================================================
class AI:
    """简单的格斗 AI: 保持距离 -> 抓机会进攻 -> 挨打会防"""
    def __init__(self, lvl=1.0):
        self.lvl = lvl
        self.timer = 0
        self.plan = {}
        self.hold = 0

    def think(self, me, foe):
        self.timer -= 1
        if self.timer > 0:
            return self.plan
        self.timer = random.randint(4, 11)
        d = abs(foe.x - me.x)
        p = {}
        # 危险: 对手在攻击中且贴近 -> 防御
        if foe.move and d < 110 and random.random() < 0.55 * self.lvl:
            self.plan = {"block": True}
            self.timer = random.randint(6, 14)
            return self.plan
        # 血少时更保守
        aggr = 0.75 if me.hp < 32 else 1.0
        if d > 150:
            p["right" if foe.x > me.x else "left"] = True
        elif d > 74:
            p["right" if foe.x > me.x else "left"] = True
            if random.random() < 0.10 * aggr:
                p["up"] = True
        else:
            r = random.random() * aggr
            if me.mp >= 50 and r < 0.24:
                p["s"] = True
            elif r < 0.52:
                p["l"] = True
            elif r < 0.74:
                p["h"] = True
            elif r < 0.86:
                p["block"] = True
            else:
                p["left" if foe.x > me.x else "right"] = True
        self.plan = p
        return p


# ==================================================================
#  UI 布局
# ==================================================================
BTN_MOVE = {
    "up":    [82, 462, 142, 522],
    "left":  [22, 506, 82, 566],
    "right": [142, 506, 202, 566],
    "down":  [82, 550, 142, 600],
}
BTN_ACT = {
    "block": [694, 532, 762, 598],
    "l":     [770, 532, 838, 598],
    "h":     [846, 532, 914, 598],
    "s":     [874, 456, 976, 524],
}
BTN_LABEL = {"up": "▲", "left": "◀", "right": "▶", "down": "▼",
             "block": "防", "l": "轻", "h": "重", "s": "必杀"}


def hit(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


# ==================================================================
#  主游戏
# ==================================================================
class Fight:
    def __init__(self, scr, touch):
        self.scr = scr
        self.touch = touch
        self.bg = make_bg()
        self.frames = [build_frames(0), build_frames(1)]
        self.sparks = {
            "red": make_spark(30, (255, 80, 60, 200)),
            "yel": make_spark(24, (255, 226, 120, 200)),
            "blu": make_spark(34, (120, 190, 255, 200)),
        }
        self.hud_imgs = self._make_hud_static()
        self.bars = self._make_bars()
        self.btn_cache = self._make_buttons()
        self.ai = AI(1.0)
        self.new_match()

    # ---------- 预渲染: 血条 / 气条 ----------
    def _make_bars(self):
        """预渲染血条/气条/掉血残影, 每帧只裁宽度 + 贴图 (rr 画圆弧太慢)"""
        out = {"hp": {}, "mp": None}
        for key, col in (("ok", (96, 226, 120)), ("warn", (240, 206, 70)),
                         ("low", (238, 80, 70))):
            im = Image.new("RGBA", (HBW, 26), (0, 0, 0, 0))
            dd = ImageDraw.Draw(im)
            rr(dd, [0, 0, HBW - 1, 25], 7, fill=col)
            dd.line([(5, 4), (HBW - 6, 4)], fill=(255, 255, 255, 95), width=3)
            out["hp"][key] = im
        # ★ 掉血残影: 原版里血一掉, 后面会留一条浅黄条慢慢缩回去
        lag = Image.new("RGBA", (HBW, 26), (0, 0, 0, 0))
        rr(ImageDraw.Draw(lag), [0, 0, HBW - 1, 25], 7, fill=(248, 226, 148))
        out["lag"] = lag
        im = Image.new("RGBA", (MBW, 11), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        rr(dd, [0, 0, MBW - 1, 10], 5, fill=(86, 174, 255))
        dd.line([(4, 3), (MBW - 5, 3)], fill=(255, 255, 255, 120), width=2)
        out["mp"] = im
        return out

    def _make_buttons(self):
        """预渲染所有按钮的 正常/按下 两种状态"""
        cache = {}
        for k, r in BTN_MOVE.items():
            cache[k] = {}
            for on in (False, True):
                fill = (70, 96, 150, 190) if not on else (120, 170, 240, 230)
                cache[k][on] = self._btn_img(r, BTN_LABEL[k], fill, 13)
        for k, r in BTN_ACT.items():
            cache[k] = {}
            if k == "block":
                base = (60, 110, 170, 190)
            elif k == "l":
                base = (70, 160, 110, 190)
            elif k == "h":
                base = (200, 120, 60, 190)
            else:
                base = (150, 70, 200, 200)
            for on in (False, True):
                c = tuple(min(255, v + 55) for v in base[:3]) + (min(255, base[3] + 40),) \
                    if on else base
                cache[k][on] = self._btn_img(r, BTN_LABEL[k], c, 15)
        return cache

    def _btn_img(self, r, label, fill, rad):
        w, h = r[2] - r[0], r[3] - r[1]
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        rr(d, [0, 0, w - 1, h - 1], rad, fill=fill, outline=(235, 240, 255, 200), width=2)
        # ★ 方向键直接画三角形 —— 板子上的文泉驿字体没有 ◀▶ 这两个字形,
        #   用文字会渲染成空心方框
        cx, cy = w / 2.0, h / 2.0
        s = min(w, h) * 0.27
        arrow = {
            "▲": [(cx, cy - s), (cx - s, cy + s * 0.75), (cx + s, cy + s * 0.75)],
            "▼": [(cx, cy + s), (cx - s, cy - s * 0.75), (cx + s, cy - s * 0.75)],
            "◀": [(cx - s, cy), (cx + s * 0.75, cy - s), (cx + s * 0.75, cy + s)],
            "▶": [(cx + s, cy), (cx - s * 0.75, cy - s), (cx - s * 0.75, cy + s)],
        }.get(label)
        if arrow:
            d.polygon([(x + 2, y + 2) for (x, y) in arrow], fill=(10, 14, 24))
            d.polygon(arrow, fill=(238, 244, 255))
            return im
        # 文字标签也一起预渲染进去
        f = font(26, bold=True, cn=True)
        try:
            tw = d.textlength(label, font=f)
        except AttributeError:
            tw = d.textsize(label, font=f)[0]
        asc, desc = f.getmetrics()
        d.text(((w - tw) / 2.0, (h - (asc + desc)) / 2.0), label, font=f,
               fill=(255, 255, 255))
        return im

    # ---------- 静态 UI 预渲染 ----------
    def _make_hud_static(self):
        """HUD 里【永远不变】的部分: 底板、头像框、血条槽、气条槽、名字、计时器框

        原版布局: 最外侧一个圆形【头像】, 往中间是长血条(带掉血残影), 下面是气条,
        正中一个圆计时器。
        """
        im = Image.new("RGBA", (W, HUD_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, HUD_H], fill=(14, 16, 30, 255))
        d.line([(0, HUD_H), (W, HUD_H)], fill=(90, 110, 170), width=2)
        # 头像
        self.port_xy = [(8, 3), (W - 8 - 58, 3)]
        self._numcache = getattr(self, "_numcache", {})
        for i, (px, py) in enumerate(self.port_xy):
            im.paste(make_portrait(CHARS[i]), (px, py), make_portrait(CHARS[i]))
        # 血条槽 (在头像右侧)
        rr(d, [PX0 - 4, 8, PX1 + 4, 38], 8, fill=(34, 26, 30),
           outline=(126, 136, 166), width=2)
        rr(d, [W - PX1 - 4, 8, W - PX0 + 4, 38], 8, fill=(34, 26, 30),
           outline=(126, 136, 166), width=2)
        # 气条槽
        rr(d, [PX0 - 2, 43, PX0 + 296, 56], 6, fill=(20, 26, 40),
           outline=(90, 105, 140), width=1)
        rr(d, [W - PX0 - 296, 43, W - PX0 + 2, 56], 6, fill=(20, 26, 40),
           outline=(90, 105, 140), width=1)
        # 计时器(圆)
        cx, cy = W // 2, 30
        d.ellipse([cx - 27, cy - 27, cx + 27, cy + 27], fill=(150, 140, 96))
        d.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], fill=(26, 28, 48))
        # 名字
        f = font(16, cn=True)
        d.text((PX0, 58), CHARS[0]["title"], font=f, fill=(226, 234, 250))
        try:
            tw = d.textlength(CHARS[1]["title"], font=f)
        except AttributeError:
            tw = d.textsize(CHARS[1]["title"], font=f)[0]
        d.text((W - PX0 - tw, 58), CHARS[1]["title"], font=f, fill=(226, 234, 250))
        return im

    def _num(self, s, size, color):
        """带缓存的数字图片

        ★ 计时器/连击数每帧都在变, 但 scr.text 一次要 5~8ms (CJK 字体渲染很贵)。
          数字只有 0~99 种可能, 预渲染一次存起来, 之后每帧只贴一张小图。
        """
        key = (s, size, color)
        im = self._numcache.get(key)
        if im is None:
            # ★ 含中文的要用中文字体, 否则渲染成空心方框
            f = font(size, bold=True, cn=any(ord(c) > 127 for c in s))
            asc, desc = f.getmetrics()
            tmp = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            try:
                tw = int(td.textlength(s, font=f)) + 4
            except AttributeError:
                tw = td.textsize(s, font=f)[0] + 4
            im = Image.new("RGBA", (tw, asc + desc), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((2, 0), s, font=f, fill=color)
            self._numcache[key] = im
        return im

    def draw_hud(self):
        scr = self.scr
        # ★ 只盖 HUD 那一条, 不能贴整屏背景(会把角色擦掉)
        scr.d.rectangle([0, 0, W, HUD_H], fill=(14, 16, 30))
        scr.img.paste(self.hud_imgs, (0, 0), self.hud_imgs)
        # 血条 / 气条: 裁预渲染图 + 贴, 不画圆弧
        #   条的填充从【外侧】开始向中心缩 (和原版一致)
        for f, right, i in ((self.f1, False, 0), (self.f2, True, 1)):
            hp = max(0.0, f.hp / float(MAX_HP))
            lag = max(0.0, min(1.0, self.hp_lag[i] / float(MAX_HP)))
            lw = int(HBW * lag)
            if lw > 1:
                im = self.bars["lag"].crop((0, 0, lw, 26))
                scr.img.paste(im, ((W - PX0 - lw) if right else PX0, 9), im)
            bw = int(HBW * hp)
            if bw > 1:
                key = "ok" if hp > 0.5 else ("warn" if hp > 0.22 else "low")
                im = self.bars["hp"][key].crop((0, 0, bw, 26))
                scr.img.paste(im, ((W - PX0 - bw) if right else PX0, 9), im)
            mpw = int(MBW * min(1.0, f.mp / float(MAX_MP)))
            if mpw > 1:
                im = self.bars["mp"].crop((0, 0, mpw, 11))
                scr.img.paste(im, ((W - PX0 - mpw) if right else PX0, 44), im)
        # 回合点 (每人 2 个, 先赢 2 局者胜) —— 画在计时器两侧
        for side, i in ((0, 0), (1, 1)):
            for k in range(2):
                on = self.wins[i] > k
                c = (255, 214, 80) if on else (72, 76, 98)
                cx = (W // 2 - 74 - k * 26) if side == 0 else (W // 2 + 74 + k * 26)
                scr.d.ellipse([cx - 9, 21, cx + 9, 39], fill=c,
                              outline=(20, 22, 34))
        # 计时 (圆盘) —— 用缓存的数字图, 不要每帧渲染文字
        im = self._num(str(int(math.ceil(self.timer))), 32, (255, 244, 210))
        scr.img.paste(im, (W // 2 - im.size[0] // 2, 29 - im.size[1] // 2), im)
        # 连击显示 (带深色描边, 压在月亮上也看得清)
        for f, right in ((self.f1, False), (self.f2, True)):
            if f.combo_hit >= 2:
                x = (W - 210) if right else 210
                im = self._num(str(f.combo_hit), 44, (255, 226, 110))
                sh = self._num(str(f.combo_hit), 44, (30, 18, 10))
                px = x - im.size[0] // 2
                py = 300 - im.size[1] // 2
                for (ox, oy) in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2), (-2, -2)):
                    scr.img.paste(sh, (px + ox, py + oy), sh)
                scr.img.paste(im, (px, py), im)
                im2 = self._num("连击", 20, (255, 244, 200))
                sh2 = self._num("连击", 20, (30, 18, 10))
                px2 = x - im2.size[0] // 2
                py2 = 340 - im2.size[1] // 2
                for (ox, oy) in ((-1, 0), (1, 0), (0, 1), (1, 1)):
                    scr.img.paste(sh2, (px2 + ox, py2 + oy), sh2)
                scr.img.paste(im2, (px2, py2), im2)

    def draw_controls(self, pressed):
        """只贴预渲染好的按钮图 (每帧不再画圆弧)"""
        scr = self.scr
        for k, r in BTN_MOVE.items():
            im = self.btn_cache[k].get(bool(pressed.get(k)))
            if im is not None:
                scr.img.paste(im, (r[0], r[1]), im)
        for k, r in BTN_ACT.items():
            im = self.btn_cache[k].get(bool(pressed.get(k)))
            if im is not None:
                scr.img.paste(im, (r[0], r[1]), im)

    # ---------- 比赛流程 ----------
    def new_match(self):
        self.wins = [0, 0]
        self.round_no = 0
        self.new_round()

    def new_round(self):
        self.round_no += 1
        self.f1 = Fighter(0, self.frames[0], 330, 1, CHARS[0]["title"])
        self.f2 = Fighter(1, self.frames[1], 694, -1, CHARS[1]["title"])
        self.projs = []
        self.effects = []
        self.timer = 60.0
        self.hp_lag = [float(MAX_HP), float(MAX_HP)]
        self.n_move_f1 = 0
        self.cnt_move = {"atk_l": 0, "atk_h": 0, "special": 0}
        self._f1_prev_move = None
        self.state = "ready"        # ready -> fight -> over
        self.state_t = 78
        self.result = ""
        self.ai = AI(1.0)

    # ---------- 一次物理/逻辑步进 ----------
    def step(self, k1):
        if self.state == "ready":
            self.state_t -= 1
            if self.state_t <= 0:
                self.state = "fight"
            return
        if self.state == "over":
            self.state_t -= 1
            if self.state_t <= 0:
                if max(self.wins) >= 2:
                    self.new_match()
                else:
                    self.new_round()
            return

        # 掉血残影: 慢慢追上真实血量
        for i, f in ((0, self.f1), (1, self.f2)):
            tgt = max(0.0, f.hp)
            if self.hp_lag[i] > tgt:
                self.hp_lag[i] = max(tgt, self.hp_lag[i] - 0.8)
            else:
                self.hp_lag[i] = tgt
        self.timer -= 1 / 30.0
        if self.timer <= 0:
            self.timer = 0
            self.finish_round()

        # 缓慢回气: 原版靠打人/挨打攒查克拉, 这里再加一点点被动回复,
        # 否则必杀经常一整局都用不出来 (玩起来很憋)
        for f in (self.f1, self.f2):
            if f.mp < MAX_MP:
                f.mp = min(float(MAX_MP), f.mp + 0.05)
        k2 = self.ai.think(self.f2, self.f1)
        self.f1.update(k1, self.f2, self.spawn_proj)
        self.f2.update(k2, self.f1, self.spawn_proj)
        # ★ 统计玩家出招次数 —— 用来客观验证"触摸按键真的生效了",
        #   光看截图很难区分是我出的招还是 AI 出的
        if self.f1.move is not None and self._f1_prev_move is None:
            self.n_move_f1 += 1
            if self.f1.move in self.cnt_move:
                self.cnt_move[self.f1.move] += 1
        self._f1_prev_move = self.f1.move

        # 分离(不许重叠)
        d = self.f2.x - self.f1.x
        need = BODY_HW * 2 + PUSH_GAP
        if abs(d) < need and abs(self.f1.y - self.f2.y) < 90:
            push = (need - abs(d)) / 2.0 + 0.5
            s = 1 if d >= 0 else -1
            self.f1.x -= s * push
            self.f2.x += s * push
            self.f1.x = max(STAGE_L, min(STAGE_R, self.f1.x))
            self.f2.x = max(STAGE_L, min(STAGE_R, self.f2.x))

        # 近战判定
        for a, b in ((self.f1, self.f2), (self.f2, self.f1)):
            ab = a.attack_box()
            if ab is None or a.hit_done:
                continue
            hb = b.hurt_box()
            if ab[0] < hb[2] and ab[2] > hb[0] and ab[1] < hb[3] and ab[3] > hb[1]:
                a.hit_done = True
                m = MOVES[a.move]
                dmg, stun, kb = m["dmg"], m["stun"], m["kb"]
                blocked = b.blocking and (b.face != a.face)
                b.take_hit(dmg, kb, stun, 1 if b.x >= a.x else -1, blocked)
                a.mp = min(MAX_MP, a.mp + m["gain"])
                self.add_effect(b.center(), "blu" if not blocked else "yel",
                                0.45 if not blocked else 0.3)
                if not blocked:
                    a.combo_hit = (a.combo_hit or 0) + 1
                    a.combo_timer = 60

        # 弹道
        for p in list(self.projs):
            keep = p.update(self.f1 if p.owner == 1 else self.f2,
                            lambda f, pr: self.proj_hit(f, pr))
            if not keep:
                self.projs.remove(p)

        # 连击计时
        for f in (self.f1, self.f2):
            if getattr(f, "combo_timer", 0) > 0:
                f.combo_timer -= 1
                if f.combo_timer <= 0:
                    f.combo_hit = 0

        # 特效
        for e in list(self.effects):
            e[2] -= 1
            if e[2] <= 0:
                self.effects.remove(e)

        # 判定本局结束
        if self.state == "fight":
            if self.f1.hp <= 0 or self.f2.hp <= 0:
                self.finish_round()

    def proj_hit(self, foe, pr):
        blocked = foe.blocking
        foe.take_hit(pr.dmg, pr.kb, pr.stun, 1 if foe.x >= pr.x else -1, blocked)
        self.add_effect(foe.center(), "red" if not blocked else "yel", 0.5)
        owner = self.f1 if pr.owner == 0 else self.f2
        if not blocked:
            owner.combo_hit = (owner.combo_hit or 0) + 1
            owner.combo_timer = 60

    def spawn_proj(self, owner, x, y, face, dmg, stun, kb, idx):
        col = CHARS[idx]["aura"]
        self.projs.append(Proj(idx, x, y, face, dmg, stun, kb, col))
        self.add_effect((x, y), "blu", 0.35)

    def add_effect(self, pos, kind, scale):
        self.effects.append([pos[0], pos[1], 10, kind, scale])

    def finish_round(self):
        self.state = "over"
        self.state_t = 110
        if self.f1.hp > self.f2.hp:
            self.wins[0] += 1
            self.result = "第一回合 · %s 胜!" % CHARS[0]["short"]
        elif self.f2.hp > self.f1.hp:
            self.wins[1] += 1
            self.result = "第一回合 · %s 胜!" % CHARS[1]["short"]
        else:
            self.result = "平局!"
        self.result = self.result.replace("第一", "第%d" % min(3, self.round_no))
        if max(self.wins) >= 2:
            who = CHARS[0]["short"] if self.wins[0] > self.wins[1] else CHARS[1]["short"]
            self.result = "%s 获胜!" % who
        self._make_over_panel()

    def _make_over_panel(self):
        """回合结算面板只渲染一次 (rrect 画圆弧 + 中文渲染都很贵,
        放在每帧里会把 30FPS 拖到 16FPS)"""
        w, h = 560, 130
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        rr(d, [0, 0, w - 1, h - 1], 16, fill=(18, 20, 38, 245),
           outline=(255, 214, 90), width=3)
        f = font(34, bold=True, cn=True)
        try:
            tw = d.textlength(self.result, font=f)
        except AttributeError:
            tw = d.textsize(self.result, font=f)[0]
        d.text(((w - tw) / 2, 16), self.result, font=f, fill=(255, 240, 190))
        s = "比分  %d : %d" % (self.wins[0], self.wins[1])
        f2 = font(24, cn=True)
        try:
            tw2 = d.textlength(s, font=f2)
        except AttributeError:
            tw2 = d.textsize(s, font=f2)[0]
        d.text(((w - tw2) / 2, 74), s, font=f2, fill=(200, 220, 255))
        self.over_img = im

    # ---------- 绘制 ----------
    def draw(self, pressed, clips=None):
        """把这一帧画进 scr.img

        ★ clip: 只在这个矩形里重画背景。以前每帧都把整屏 1024x600 背景 paste
          一遍(61 万像素), 而真正 flush 到显存的只有脏矩形那一小块 ——
          绝大部分 paste 是白做的。传了 clip 就只贴那一块。
        """
        scr = self.scr
        if not clips:
            scr.img.paste(self.bg, (0, 0))
        else:
            for (x0, y0, x1, y1) in clips:
                if x1 > x0 + 1 and y1 > y0 + 1:
                    scr.img.paste(self.bg.crop((x0, y0, x1, y1)), (x0, y0))
        for p in self.projs:
            p.draw(scr)
        # 远的先画
        order = [self.f1, self.f2]
        order.sort(key=lambda f: f.y)
        for f in order:
            f.draw(scr)
        # 特效
        for e in self.effects:
            sp = self.sparks.get(e[3], self.sparks["yel"])
            k = e[2] / 10.0
            sz = max(8, int(sp.size[0] * (0.5 + e[4] * (1.4 - k))))
            s2 = sp.resize((sz, sz))
            scr.img.paste(s2, (int(e[0] - sz / 2), int(e[1] - sz / 2)), s2)
        self.draw_controls(pressed)
        self.draw_hud()
        # 提示文字
        if self.state == "ready":
            n = 3 if self.state_t > 52 else (2 if self.state_t > 26 else 1)
            scr.text((W // 2, 250), str(n), 130, (255, 236, 160), bold=True, anchor="mm")
            scr.text((W // 2, 340), "READY", 42, (255, 255, 255), bold=True, anchor="mm")
        elif self.state == "over":
            if getattr(self, "over_img", None) is not None:
                scr.img.paste(self.over_img,
                              (W // 2 - self.over_img.size[0] // 2, 205),
                              self.over_img)

    def combo_box(self):
        """连击数所在区域 —— 必须算进脏矩形, 否则数字不会被刷到屏幕上,
        或者走掉之后留一片残影"""
        out = []
        for f, right in ((self.f1, False), (self.f2, True)):
            if f.combo_hit >= 2:
                x = (W - 210) if right else 210
                out.append((x - 120, 260, x + 120, 380))
        return out

    # ---------- 脏矩形 ----------
    def dirty_boxes(self, prev):
        """返回若干个【小】脏矩形

        ★ 以前是把所有东西并成一个大框再 flush。两个角色一旦分开, 并集就
          等于整屏, 每帧白白多刷好几倍面积。拆成多块(相近的合并)之后,
          刷新的总面积基本等于真正变化的部分。
        """
        boxes = [f.bbox() for f in (self.f1, self.f2)] + list(prev) + self.combo_box()
        for p in self.projs:
            boxes.append(p.bbox())
        for e in self.effects:
            boxes.append((e[0] - 46, e[1] - 46, e[0] + 46, e[1] + 46))
        out = []
        for b in boxes:
            x0 = max(0, int(b[0]))
            y0 = max(HUD_H + 2, int(b[1]))
            x1 = min(W, int(b[2]))
            y1 = min(H, int(b[3]))
            if x1 > x0 and y1 > y0:
                out.append([x0, y0, x1, y1])
        # 互相靠得近的就合并, 免得下来回切太碎
        merged = True
        while merged and len(out) > 1:
            merged = False
            for i in range(len(out)):
                for j in range(i + 1, len(out)):
                    a, c = out[i], out[j]
                    if not (a[2] + 20 < c[0] or c[2] + 20 < a[0] or
                            a[3] + 20 < c[1] or c[3] + 20 < a[1]):
                        out[i] = [min(a[0], c[0]), min(a[1], c[1]),
                                  max(a[2], c[2]), max(a[3], c[3])]
                        out.pop(j)
                        merged = True
                        break
                if merged:
                    break
        return [tuple(b) for b in out]

    def dirty_box(self, prev):
        bs = self.dirty_boxes(prev)
        if not bs:
            return (0, HUD_H + 2, W, H)
        return (min(b[0] for b in bs), min(b[1] for b in bs),
                max(b[2] for b in bs), max(b[3] for b in bs))

    def dirty_box_txt(self, prev):
        """过渡帧(READY / 回合结束)会画中央大字, 脏区要覆盖到"""
        b = list(self.dirty_box(prev))
        b[0] = min(b[0], W // 2 - 280)
        b[2] = max(b[2], W // 2 + 280)
        b[1] = min(b[1], 180)
        b[3] = max(b[3], 360)
        return tuple(b)


# ==================================================================
#  入口
# ==================================================================
def run(scr, touch):
    g = Fight(scr, touch)
    # 先把静态部分画好并整屏推一次
    g.draw({})
    scr.flush()
    time.sleep(0.15)

    prev = []
    hud_prev = None
    ctrl_prev = None
    prev_state = None
    frame = 0
    t_last = time.time()
    while True:
        # ★ 帧边界暂停(见 apps_mc.py 里的说明)
        if os.path.exists("/tmp/fight_pause"):
            time.sleep(0.04)
            continue
        t0 = time.time()
        # ---- 收输入 ----
        # ★ 两个坑:
        #   1) 注入的点击是 'tap' 类型, 不能只认 'down'/'move'
        #   2) 手指按住不动时触摸驱动【不再发事件】, 所以不能"靠事件"判断按键,
        #      必须排空事件队列后, 用"当前按在哪"的状态来判断
        back = False
        press_xy = None
        while True:
            ev = touch.poll(move=True)
            if ev is None:
                break
            kind, tx, ty = ev
            if kind in ("down", "tap"):
                press_xy = (tx, ty)
            elif kind == "move" and press_xy is not None:
                press_xy = (tx, ty)
            elif kind == "up":
                press_xy = None
        # 真实触摸按住不放时没有新事件, 用 touch.down + 当前坐标兜底
        if press_xy is None and getattr(touch, "down", False):
            press_xy = (touch.x, touch.y)

        pressed = {}
        if press_xy is not None:
            tx, ty = press_xy
            if 0 <= tx <= 108 and 0 <= ty <= 62:
                back = True
            else:
                for k, r in BTN_MOVE.items():
                    if hit(r, tx, ty):
                        pressed[k] = True
                for k, r in BTN_ACT.items():
                    if hit(r, tx, ty):
                        pressed[k] = True
        # ---- 步进 ----
        if back:
            return
        g.step(pressed)
        # ---- 绘制 ----
        boxes = (g.dirty_boxes(prev) if g.state == "fight"
                 else [g.dirty_box_txt(prev)])
        g.draw(pressed, boxes)
        for bx in boxes:
            scr.flush(box=bx)
        # ★ 状态切换时整屏推一次 —— 否则 READY / 回合结束的中央大字
        #   不会被局部刷新覆盖, 会一直留在屏幕上(踩过)
        if g.state != prev_state:
            scr.flush()
            prev_state = g.state
        prev = [f.bbox() for f in (g.f1, g.f2)]
        # HUD / 控件变化时单独补推
        hud_now = (int(g.f1.hp), int(g.f2.hp), int(g.f1.mp), int(g.f2.mp),
                   int(g.timer), g.wins[0], g.wins[1], g.state)
        if hud_now != hud_prev:
            scr.flush(box=(0, 0, W, HUD_H + 2))
            hud_prev = hud_now
        ctrl_now = tuple(sorted(pressed.items()))
        if ctrl_now != ctrl_prev:
            scr.flush(box=(0, 452, W, H))
            ctrl_prev = ctrl_now
        # ---- 帧率控制 ----
        frame += 1
        dt = time.time() - t0
        if dt < 1 / 32.0:
            time.sleep(1 / 32.0 - dt)
        # 统计实际帧率, 写文件方便外部读取
        if frame % 20 == 0:
            now = time.time()
            fps = 20.0 / max(1e-6, now - t_last)
            t_last = now
            try:
                with open("/tmp/fight_fps", "w") as fh:
                    fh.write("%.1f  state=%s  玩家出招=%d (轻%d 重%d 必杀%d)  "
                             "气=%.0f  hp=%.0f/%.0f\n"
                             % (fps, g.state, g.n_move_f1,
                                g.cnt_move["atk_l"], g.cnt_move["atk_h"],
                                g.cnt_move["special"], g.f1.mp,
                                g.f1.hp, g.f2.hp))
            except Exception:
                pass
