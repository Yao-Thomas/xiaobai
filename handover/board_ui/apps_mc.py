#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_mc.py —— 自己写的 MC（体素空间渲染 / C 实现 / 触屏操作）

为什么 Craft / Minetest 只有 1-3 FPS, 而这个能跑 20+:
    那两者用【多边形渲染】, 把世界切成几十万个三角形丢给 OpenGL。本机没有 3D
    硬件, 纯 CPU 的 llvmpipe 实测只有 ~17 万三角形/秒 -> 必然个位数帧率。

    这里换成【体素空间渲染】(Voxel Space / Comanche 算法, 参考
    https://github.com/s-macke/VoxelSpace ):
    对屏幕每一列沿视线在高度图上推进, 找到挡住的地方就画一条竖直线段。
    * 完全没有三角形
    * 绘制 = 往缓冲区里填一段连续字节
    * 用【颜色图】而不是"高度->颜色"渐变: 颜色图里已经烘焙好明暗和材质,
      渲染时只查一次表, 不算光照 —— 这是画面有细节、不像一坨色块的关键

    渲染核心用 C 写 (mcrender.c -> libmcrender.so):
    板子上的 Python 实测只有约 190 万次简单循环/秒 (667MHz Cortex-A9),
    纯 Python 每帧几万次内循环根本跑不动。C 版可以 512x300 渲染 + 2 倍放大。

代价: 它画的是"高度场地形", 不是完整的方块体素 ——
      可以自由飞行、挖山、填坑、看风景, 但没有悬空方块和洞穴。
      这是在这块没有 3D 硬件的板子上唯一能做到流畅的 3D 方案。

操作:
   左半屏拖动  —— 前进/后退/左右平移
   右半屏拖动  —— 转头 / 俯仰
   右下按钮    —— 挖 / 放 / 升 / 降
   左上【返回】按钮 —— 回桌面

=== 2026-09-25 修的四个问题 ===
  1. 退不出去: 以前只在 press_xy 上判断返回, 而触摸驱动会把 down 和 up
     放在同一批事件里, 这一帧 press_xy 被 up 清成 None -> 快速点击永远
     丢。现在用 click 变量单独记"本帧按下过哪里", up 不清它。
     同时加了一个看得见的【返回】按钮(以前只有左上角一块隐形区域)。
  2. 一直颤抖: 手指的 1~2 像素抖动会直接变成相机位移/转角, 而体素渲染
     对位置非常敏感(近处一格高度差 -> 几百像素的条带跳动)。现在加了
     3 像素死区 + 速度低通滤波, 手不动就不动。
  3. 抖动(judder): 移动以前是"每帧固定量", 帧率在 22~28 波动 -> 速度
     也跟着波动。现在全部按 dt 积分。
  4. 上下颠簸: 以前走到高处 z 会瞬间吸附到地面高度, 整个世界跟着跳。
     现在平滑逼近。
另外把 HUD 的 21ms 砍到 ~4ms(见 _make_hud/blit_raw), 帧率从 22 上去了。
"""
import ctypes
import math
import os
import random
import time

from PIL import Image, ImageDraw, ImageFilter

from fbui import font

W, H = 1024, 600

# ---------------- 渲染分辨率 (C 侧渲染, 再整数倍放大) ----------------
# ---------------- 渲染分辨率 ----------------
# ★ 原生 1024x600: 以前是 512x300 再放大 2 倍, 每个"像素"其实是 2x2 的块,
#   看着又糊又块。改成原生之后射线步数翻倍(每步只服务 1 列), 但放大那一步
#   省掉了, 总耗时差不多, 画面锐利得多。
RW, RH = 1024, 600
QUANT = 8                       # ★ 高度量化台阶 = 一个方块的高度(世界单位)
                                #   挖/放一次正好 ±QUANT, 所以正好是一个方块
FOCAL = 600.0                   # 焦距(像素)。= RW/2/tan(40.5°) 保持原来的视场角
# ★★ 竖直缩放必须满足 HSCALE = 1/QUANT, 否则方块不是立方体:
#    方块宽 = 1 格, 方块高(视觉) = QUANT*HSCALE。要像立方体就得 QUANT*HSCALE≈1。
HSCALE = 1.0 / QUANT
EYE = 22.0                      # 眼高(世界单位) = EYE*HSCALE ≈ 2.75 个方块
MAXD = 200                      # 视距(步数)
REACH = 32                      # 挖/放的最远距离(步)

MAP_BITS = 9
MAP_SIZE = 1 << MAP_BITS
MAP_MASK = MAP_SIZE - 1

# ---------------- 手感参数 ----------------
DZ = 3.0                        # 触摸死区(像素): 小于这个的抖动一律忽略
EYE = 30.0                      # 眼高(高于地面多少级台阶; 太低会像被墙围住)
SPEED = 120.0                   # 移动速度 (单位/秒)
VSPEED = 130.0                  # 升降速度 (单位/秒)
YAW_RATE = 1.9                  # 满偏转时的转头速度 (弧度/秒)
PITCH_RATE = 1.2                # 满偏转时的俯仰速度 (弧度/秒)
SMOOTH = 0.55                   # 速度低通系数 (越小越平滑、越滞后)

LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "libmcrender.so")
_lib = None


def getlib():
    global _lib
    if _lib is not None:
        return _lib
    lib = ctypes.CDLL(LIB_PATH)
    ub = ctypes.POINTER(ctypes.c_ubyte)
    lib.mc_init.argtypes = [ub, ctypes.c_int]
    lib.mc_init.restype = None
    lib.mc_setres.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_float]
    lib.mc_setres.restype = None
    lib.mc_set_skip.argtypes = [ctypes.c_int] * 5
    lib.mc_set_skip.restype = None
    lib.mc_render.argtypes = [ub, ctypes.c_float, ctypes.c_float, ctypes.c_float,
                              ctypes.c_float, ctypes.c_float, ctypes.c_int]
    lib.mc_render.restype = None
    # ★ 直接写 framebuffer 的版本 (省掉 Python 侧整屏转换)
    lib.mc_render_bgr.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                  ctypes.c_float, ctypes.c_float, ctypes.c_float,
                                  ctypes.c_float, ctypes.c_float, ctypes.c_int]
    lib.mc_render_bgr.restype = None
    lib.mc_pick.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float,
                            ctypes.c_float, ctypes.c_float, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int),
                            ctypes.POINTER(ctypes.c_int),
                            ctypes.POINTER(ctypes.c_int)]
    lib.mc_pick.restype = ctypes.c_int
    lib.mc_cell.argtypes = [ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int),
                            ctypes.POINTER(ctypes.c_int)]
    lib.mc_cell.restype = ctypes.c_int
    lib.mc_rebake.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.mc_rebake.restype = None
    lib.mc_set_hscale.argtypes = [ctypes.c_float]
    lib.mc_set_hscale.restype = None
    lib.mc_set_edge.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_int]
    lib.mc_set_edge.restype = None
    lib.mc_set_highlight.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.mc_set_highlight.restype = None
    lib.mc_set_water.argtypes = [ctypes.c_int]
    lib.mc_set_water.restype = None
    lib.mc_set_phase.argtypes = [ctypes.c_int]
    lib.mc_set_phase.restype = None
    lib.mc_set_mat.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
    lib.mc_set_mat.restype = None
    _lib = lib
    return lib


# ---------------- 方块类型 (编号必须和 mcrender.c 的 BAND_COL 一致) ----------------
B_DEEPWATER, B_WATER, B_SAND, B_GRASS, B_FOREST, B_ROCK, B_SNOW = 0, 1, 2, 3, 4, 5, 6
B_WOOD, B_LEAF, B_STONE, B_SAND2, B_SNOWB = 7, 8, 9, 10, 11
# 玩家可以放置的方块 (名字, 编号, 用于按钮的 RGB)
MATERIALS = [
    ("草", B_GRASS,  (96, 160, 76)),
    ("沙", B_SAND2,  (232, 216, 168)),
    ("石", B_STONE,  (158, 154, 146)),
    ("木", B_WOOD,   (124, 86, 50)),
    ("叶", B_LEAF,   (48, 118, 44)),
    ("雪", B_SNOWB,  (250, 250, 255)),
]
TREE_COUNT = 320                # 种多少棵树


def make_trees(hm, mat, count=TREE_COUNT, seed=777, avoid=None, avoid_r=16):
    """在草地上种树

    高度场表达不了"悬空"和"这是什么方块", 所以树是这样做的:
      树干 = 中间那一格抬高 8 级台阶 + 材质改成原木
      树冠 = 周围一圈抬高 6 级(3x3)和 4 级(5x5 外圈) + 材质改成树叶
    逐级递减是为了不在树周围留下一圈陡崖。
    avoid = 出生点, 附近 avoid_r 格内不种树 (否则一开局就卡在树里)。
    """
    random.seed(seed)
    n = 0
    tries = 0
    while n < count and tries < count * 40:
        tries += 1
        x = random.randrange(MAP_SIZE)
        y = random.randrange(MAP_SIZE)
        i = y * MAP_SIZE + x
        h = hm[i]
        if not (BAND_LO[B_GRASS] <= h <= BAND_HI[B_GRASS]):
            continue
        if mat[i]:                       # 已经种过了
            continue
        if avoid is not None:
            dx = x - avoid[0]
            dy = y - avoid[1]
            dx -= MAP_SIZE * round(dx / MAP_SIZE)
            dy -= MAP_SIZE * round(dy / MAP_SIZE)
            if dx * dx + dy * dy < avoid_r * avoid_r:
                continue
        dirts = []
        ok = True
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                j = ((y + dy) & MAP_MASK) * MAP_SIZE + ((x + dx) & MAP_MASK)
                if mat[j]:               # 和别的树重叠
                    ok = False
                dirts.append((j, max(abs(dx), abs(dy))))
        if not ok:
            continue
        for j, r in dirts:
            # ★ 高度场做不出"树干 + 悬空树冠", 只能做成【圆冠树包】:
            #   外圈 +4、内圈 +5、中心 +5(原木)。中心【不能】比内圈高,
            #   否则树干会从树冠里戳出来, 远看就是一根绿电线杆。
            if r == 0:
                hm[j] = min(255, hm[j] + 5 * QUANT)
                mat[j] = B_WOOD + 1
            elif r == 1:
                hm[j] = min(255, hm[j] + 5 * QUANT)
                mat[j] = B_LEAF + 1
            else:
                hm[j] = min(255, hm[j] + 4 * QUANT)
                mat[j] = B_LEAF + 1
        n += 1
    return n


# 各类型的"自动材质"高度区间 (和 C 里 BAND_OF 的阈值对应)
BAND_TH = (39, 58, 76, 175, 207, 229)
BAND_LO = (0, 39, 58, 76, 175, 207, 229)
BAND_HI = (38, 57, 75, 174, 206, 228, 255)


def make_heightmap(seed=20260924, size=MAP_SIZE, max_base=96, blur=3.0,
                   lo_pct=6, hi_pct=249, gamma=1.0, quant=0):
    """多倍频噪声地形

    ★ 两个约束:
      1) 坡度: 体素渲染屏幕上一段的竖直跨度 ≈ Δh*焦距*竖直缩放/距离。
         相邻格差 3, 在距离 50 处就是 8 像素的跳变; 差 20 就整屏乱跳。
         官方 Comanche 高度图相邻格平均只有约 0.25。
         所以只保留低频倍频 + 一次强模糊。
      2) ★ quant: 高度【量化成台阶】。平滑高度场渲染出来是光滑山坡,
         量化之后每一级台阶就是【一个方块】—— 台阶侧面被坡向明暗压暗,
         台阶顶面被提亮, 才有"我的世界"的方块感。
    """
    random.seed(seed)
    acc = None
    tot = 0.0
    base = 4
    w = 0.55
    while base <= max_base:
        small = Image.new("L", (base, base))
        small.putdata([random.randint(0, 255) for _ in range(base * base)])
        big = small.resize((size, size), Image.BICUBIC)
        if acc is None:
            acc = big
            tot = w
        else:
            acc = Image.blend(acc, big, w / (tot + w))
            tot += w
        base *= 2
        w *= 0.62
    if blur > 0:
        acc = acc.filter(ImageFilter.GaussianBlur(blur))
    g = acc.load()
    vals = [g[x, y] for y in range(0, size, 3) for x in range(0, size, 3)]
    vals.sort()
    lo = vals[int(len(vals) * 0.01)]
    hi = vals[int(len(vals) * 0.99)]
    if hi - lo < 8:
        hi = lo + 8
    # 一张 LUT 同时做: 拉伸到 [lo_pct, hi_pct] + 量化到台阶
    q = max(0, int(quant))
    lut = []
    for v in range(256):
        t = (v - lo) / float(hi - lo)
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        if gamma != 1.0:
            t = t ** gamma
        h = int(lo_pct + t * (hi_pct - lo_pct))
        if q > 1:
            h = (h // q) * q + q // 2      # 台阶, 取台阶中间值
        lut.append(max(1, min(255, h)))
    return bytearray(acc.point(lut).tobytes())


def map_gradient(hm, size=MAP_SIZE, step=2):
    """相邻格平均/最大高度差 —— 调地形时看这个数(官方约 0.25)"""
    s = n = mx = 0
    for y in range(0, size, step):
        r = y * size
        for x in range(0, size - 1, step):
            d = abs(hm[r + x + 1] - hm[r + x])
            s += d
            n += 1
            if d > mx:
                mx = d
    return s / float(n or 1), mx


def hit(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


class MC:
    # ---- HUD 布局 ----
    BAR_H = 96                                  # 顶部信息栏高度
    BTN_BACK = (12, 10, 132, 50)                # 返回按钮(看得见的!)
    BACK_HIT = (0, 0, 150, 58)                  # 实际判定区域(放宽一点好按)
    INFO_XY = (12, 60)                          # 实时数据文字位置
    INFO_WH = (500, 34)
    MSG_WH = (420, 34)                          # 提示文字(右对齐)

    # ---- 操作按钮 ----
    CTRL_X = W - 260
    CTRL_Y = H - 184
    BTN_DIG = [W - 252, H - 184, W - 136, H - 110]
    BTN_PUT = [W - 124, H - 184, W - 8, H - 110]
    BTN_UP = [W - 252, H - 92, W - 136, H - 18]
    BTN_DN = [W - 124, H - 92, W - 8, H - 18]

    # ---- 方块选择条 (在操作按钮上方) ----
    MATBAR_XY = (W - 260, H - 240)
    MATBAR_WH = (260, 48)
    MAT_SEL = 0                     # 当前选中的方块

    def mat_rect(self, i):
        x, y = self.MATBAR_XY
        return (x + 6 + i * 50, y + 8, x + 6 + i * 50 + 43, y + 40)

    def __init__(self, scr, touch):
        self.scr = scr
        self.touch = touch
        t0 = time.time()
        self.hm = make_heightmap(quant=QUANT)
        self.mat = bytearray(MAP_SIZE * MAP_SIZE)
        self.x, self.y = self._find_spawn()
        # ★ 先定出生点再种树, 免得一开局就卡在树干里
        self.ntrees = make_trees(self.hm, self.mat, avoid=(self.x, self.y))
        self.lib = getlib()
        self.hmbuf = (ctypes.c_ubyte * len(self.hm)).from_buffer(self.hm)
        self.matbuf = (ctypes.c_ubyte * len(self.mat)).from_buffer(self.mat)
        self.lib.mc_init(self.hmbuf, MAP_BITS)
        self.lib.mc_set_mat(self.matbuf)
        self.lib.mc_setres(RW, RH, W, H, FOCAL)
        self.lib.mc_set_hscale(HSCALE)
        self.lib.mc_set_edge(1, 0.70, 6)
        self.lib.mc_set_water(1)
        # 让 C 跳过被 HUD / 按钮盖住的区域, 别白画(省 ~1/4 的显存写入)
        self.lib.mc_set_skip(self.BAR_H, self.CTRL_X, self.MATBAR_XY[1], W, H)
        self.out = (ctypes.c_ubyte * (W * H * 3))()
        self.outp = ctypes.cast(self.out, ctypes.POINTER(ctypes.c_ubyte))
        # framebuffer 指针: 让 C 直接把地形画进显存
        self.fbp = ctypes.addressof(ctypes.c_char.from_buffer(scr.mm))
        self.fbstride = scr.stride

        # 出生点: 找一块草地(高度适中)且有起伏的地方
        self.x, self.y = self._find_spawn()
        self.z = float(self.hm[(int(self.y) & MAP_MASK) * MAP_SIZE
                               + (int(self.x) & MAP_MASK)]) + EYE
        self.yaw = 0.0
        self.pitch = -0.30
        self.aim = None

        self.keys = {"dig": False, "put": False, "up": False, "dn": False}
        self.mv = (0.0, 0.0)                # 本帧原始速度
        self.look = (0.0, 0.0)
        self.mv_s = (0.0, 0.0)              # 滤波后的速度
        self.look_s = (0.0, 0.0)
        self.ref = None                     # 拖动参考点(死区累积用)
        self.msg = ""
        self.msg_t = 0
        self.fps = 0.0
        self.fly = False
        self.prev_t = time.time()

        # ---- 静态 UI: 全部预转成显存字节, 每帧只做内存写 ----
        self.bar = self._make_bar()
        self.bar_raw = scr.to_raw(self.bar)
        self.ctrl = self._make_ctrl()
        self.ctrl_raw = scr.to_raw(self.ctrl)
        self.matbar_raw = scr.to_raw(self._make_matbar())
        self.info = Image.new("RGB", self.INFO_WH, (10, 10, 10))
        self.d_info = ImageDraw.Draw(self.info)
        self.info_raw = None
        self.msgimg = Image.new("RGB", self.MSG_WH, (10, 10, 10))
        self.d_msg = ImageDraw.Draw(self.msgimg)
        self.msg_raw = None
        self._msg_shown = None
        self.dup = 0                        # 信息栏重绘节流计数
        self.gen_ms = (time.time() - t0) * 1000
        print("MC ready in %.0f ms" % self.gen_ms, flush=True)

    def _find_spawn(self):
        """找一块【开阔平坦】的草地出生

        以前只挑"高度最接近 95"的格子, 结果经常出生在山坳里, 一睁眼就是
        一堵绿墙。现在把"周围有多高"也算进代价: 附近有一圈高地形就扣分。
        """
        best, bx, by = 1e9, MAP_SIZE // 2, MAP_SIZE // 2
        for _ in range(4000):
            tx = random.randrange(MAP_SIZE)
            ty = random.randrange(MAP_SIZE)
            h = self.hm[ty * MAP_SIZE + tx]
            cost = abs(h - 95) * 3.0
            # 周围 12 格内最高有多高: 越高越不想在这里出生
            for r in (6, 10, 14):
                for k in range(-r, r + 1, max(1, r // 3)):
                    for (dx, dy) in ((k, -r), (k, r), (-r, k), (r, k)):
                        hh = self.hm[((ty + dy) & MAP_MASK) * MAP_SIZE
                                     + ((tx + dx) & MAP_MASK)]
                        if hh > h:
                            cost += (hh - h) * 0.35
            if cost < best:
                best, bx, by = cost, tx, ty
                if cost < 4:
                    break
        return float(bx), float(by)

    # ---------- 静态 UI ----------
    def _make_bar(self):
        """顶部信息栏(含返回按钮) —— 画一次, 之后直接 blit 字节"""
        im = Image.new("RGB", (W, self.BAR_H), (10, 10, 10))
        d = ImageDraw.Draw(im)
        # 返回按钮
        bx0, by0, bx1, by1 = self.BTN_BACK
        d.rectangle([bx0, by0, bx1, by1], fill=(46, 66, 104),
                    outline=(150, 180, 220))
        d.polygon([(bx0 + 16, (by0 + by1) // 2),
                   (bx0 + 30, by0 + 10), (bx0 + 30, by1 - 10)],
                  fill=(243, 243, 243))
        d.text((bx0 + 40, by0 + 8), "返回", font=font(20, bold=True, cn=True),
               fill=(243, 243, 243))
        # 标题
        d.text((150, 18), "自己写的 MC", font=font(20, cn=True),
               fill=(200, 220, 245))
        # 分隔线
        d.rectangle([0, 57, W, 59], fill=(120, 150, 190))
        return im

    def _make_ctrl(self):
        """按钮也做成不透明 RGB"""
        im = Image.new("RGB", (260, 184), (10, 10, 10))
        d = ImageDraw.Draw(im)
        f = font(26, bold=True, cn=True)
        for lbl, col, ox, oy in (("挖", (200, 110, 70), 0, 0),
                                 ("放", (70, 170, 110), 128, 0),
                                 ("升", (70, 130, 210), 0, 92),
                                 ("降", (120, 110, 190), 128, 92)):
            x0, y0 = 8 + ox, 8 + oy
            d.rectangle([x0, y0, x0 + 116, y0 + 74], fill=col,
                        outline=(244, 244, 244))
            d.text((x0 + 44, y0 + 20), lbl, font=f, fill=(255, 255, 255))
        return im

    def _make_matbar(self):
        """方块选择条 —— 选中的那个加白框。只有切换时才重画"""
        im = Image.new("RGB", self.MATBAR_WH, (10, 10, 10))
        d = ImageDraw.Draw(im)
        f = font(17, bold=True, cn=True)
        for i, (name, band, col) in enumerate(MATERIALS):
            r = self.mat_rect(i)
            x0 = r[0] - self.MATBAR_XY[0]
            y0 = r[1] - self.MATBAR_XY[1]
            x1 = r[2] - self.MATBAR_XY[0]
            y1 = r[3] - self.MATBAR_XY[1]
            sel = (i == self.MAT_SEL)
            d.rectangle([x0, y0, x1, y1], fill=col,
                        outline=(255, 255, 255) if sel else (77, 77, 77),
                        width=3 if sel else 1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2 + 1), name, font=f,
                   fill=(20, 20, 20) if sum(col) > 380 else (255, 255, 255),
                   anchor="mm")
        return im

    # ---------- 输入 ----------
    def in_ctrl(self, x, y):
        return x >= self.CTRL_X and y >= self.MATBAR_XY[1]

    def handle(self, press_xy):
        """根据本帧指针位置算出 move/look 速度

        ★ 死区: 只有相对参考点移动超过 DZ 像素才算数, 并且【只有超过才推进
          参考点】—— 否则手指慢慢移动时每一帧的位移都被丢掉, 画面永远不动。
        """
        self.keys = {"dig": False, "put": False, "up": False, "dn": False}
        self.mv = (0.0, 0.0)
        self.look = (0.0, 0.0)
        if press_xy is None:
            self.ref = None
            return
        x, y = press_xy
        if self.in_ctrl(x, y):
            for k, r in (("dig", self.BTN_DIG), ("put", self.BTN_PUT),
                         ("up", self.BTN_UP), ("dn", self.BTN_DN)):
                if hit(r, x, y):
                    self.keys[k] = True
                    break
            else:
                # 方块选择条
                for i in range(len(MATERIALS)):
                    if hit(self.mat_rect(i), x, y):
                        if i != self.MAT_SEL:
                            self.MAT_SEL = i
                            self.matbar_raw = self.scr.to_raw(self._make_matbar())
                        break
            self.ref = None
            return
        if self.ref is None:
            self.ref = (x, y)
            return
        rx, ry = self.ref
        dx = x - rx
        dy = y - ry
        if abs(dx) > DZ:
            rx = x
        else:
            dx = 0.0
        if abs(dy) > DZ:
            ry = y
        else:
            dy = 0.0
        self.ref = (rx, ry)
        if not dx and not dy:
            return
        vx = max(-1.0, min(1.0, dx / 55.0))
        vy = max(-1.0, min(1.0, dy / 55.0))
        if x < W // 2:
            self.mv = (vx, vy)
        else:
            self.look = (vx, vy)

    def aim_raw(self):
        """准星真正打到的方块; 没打到返回 None (只用于高亮显示)"""
        ox = ctypes.c_int(0)
        oy = ctypes.c_int(0)
        oz = ctypes.c_int(0)
        r = self.lib.mc_pick(self.x, self.y, self.z, self.yaw, self.pitch, REACH,
                             ctypes.byref(ox), ctypes.byref(oy), ctypes.byref(oz))
        return (ox.value, oy.value, oz.value) if r == 0 else None

    def pick(self):
        """挖/放的目标: 准星打的方块; 打不到就退回正前方 REACH 处那一格

        ★ 射线按【视线】走(含俯仰), 和准星严格一致。以前只沿 yaw 直线走、
          忽略俯仰, 于是准星指着脚边它却去捡很远的一格, "放一块"就变成了
          在远处凭空竖一根细柱子 —— 看着就是"一条线"。
        """
        t = self.aim_raw()
        if t:
            return t
        ix = int(self.x + math.sin(self.yaw) * REACH) & MAP_MASK
        iy = int(self.y + math.cos(self.yaw) * REACH) & MAP_MASK
        return (ix, iy, self.hm[iy * MAP_SIZE + ix])

    # ---------- 信息栏(节流重绘) ----------
    def _draw_info(self):
        d = self.d_info
        d.rectangle([0, 0, self.INFO_WH[0], self.INFO_WH[1]], fill=(10, 10, 10))
        gh = self.hm[(int(self.y) & MAP_MASK) * MAP_SIZE + (int(self.x) & MAP_MASK)]
        d.text((4, 4),
               "X %-4.0f Y %-4.0f  ALT %-4.0f  YAW %-3.0f  %2.0f FPS%s"
               % (self.x, self.y, self.z - gh,
                  math.degrees(self.yaw) % 360, self.fps,
                  "  [飞行]" if self.fly else ""),
               font=font(19, bold=True), fill=(243, 243, 243))
        self.info_raw = self.scr.to_raw(self.info)

    def _draw_msg(self):
        d = self.d_msg
        d.rectangle([0, 0, self.MSG_WH[0], self.MSG_WH[1]], fill=(10, 10, 10))
        if self.msg_t > 0:
            # ★ 用和按钮同一个字体调用(粗体+中文); 非粗体的那个字体键
            #   在某些字号下会退化成缺字方框
            d.text((self.MSG_WH[0] - 8, 5), self.msg,
                   font=font(21, bold=True, cn=True), fill=(255, 240, 170),
                   anchor="ra")
        self.msg_raw = self.scr.to_raw(self.msgimg)

    # ---------- 一帧 ----------
    def frame(self):
        """只渲染地形, 返回 PIL 图 (给截图/测试用)"""
        self.lib.mc_render(self.outp, self.x, self.y, self.z,
                           self.yaw, self.pitch, MAXD)
        return Image.frombytes("RGB", (W, H), bytes(self.out))

    # ---------- 主循环 ----------
    def run(self):
        scr = self.scr
        touch = self.touch
        press_xy = None
        frame = 0
        t_fps = time.time()
        self.prev_t = time.time()
        while True:
            # ★ 帧边界暂停: 测试脚本 touch /tmp/mc_pause 就能冻住画面。
            #   为什么不用 SIGSTOP: C 渲染是一次很长的调用, 信号要到下一个
            #   调度点才生效, 结果会停在一帧的中间 —— 截出来就是半成品
            #   (左边有地形右边还是天), 看着像个渲染 bug。
            if os.path.exists("/tmp/mc_pause"):
                time.sleep(0.04)
                self.prev_t = time.time()
                continue
            t0 = time.time()
            fdt = t0 - self.prev_t
            self.prev_t = t0
            if fdt < 0.004:
                fdt = 0.004
            if fdt > 0.08:
                fdt = 0.08

            # ---- 收输入 ----
            click = None            # ★ 本帧按下过哪里(up 不清它, 见文件头说明)
            tap_xy = None           # ★ 一次性的注入点击, 只作用这一帧
            while True:
                ev = touch.poll(move=True)
                if ev is None:
                    break
                kind, tx, ty = ev
                if kind in ("down", "tap"):
                    press_xy = (tx, ty)
                    self.ref = (tx, ty)
                    click = (tx, ty)
                    if kind == "tap":
                        tap_xy = (tx, ty)
                elif kind == "move" and press_xy is not None:
                    press_xy = (tx, ty)
                elif kind == "up":
                    press_xy = None
            held = bool(getattr(touch, "down", False))
            if held:
                # 手指按住不动时驱动不再发事件, 用当前坐标兜底
                if press_xy is None and not self.in_ctrl(touch.x, touch.y):
                    press_xy = (touch.x, touch.y)
                    if click is None:
                        click = (touch.x, touch.y)
            else:
                # ★ 没有按下的手指 -> 一律清掉, 只留这一帧的注入点击。
                #   以前不清, 一旦丢了 up 事件(或注入的 tap 本来就没有 up),
                #   按钮就会一直"卡住", 每帧都在挖/放。
                press_xy = tap_xy

            # ★ 返回: 用 click 判定 —— 快速一点也能退出去
            if click and hit(self.BACK_HIT, click[0], click[1]):
                return
            self.handle(press_xy)

            # ---- 速度低通滤波 (消掉手指抖动的毛刺) ----
            a = SMOOTH
            self.mv_s = (self.mv_s[0] + (self.mv[0] - self.mv_s[0]) * a,
                         self.mv_s[1] + (self.mv[1] - self.mv_s[1]) * a)
            self.look_s = (self.look_s[0] + (self.look[0] - self.look_s[0]) * a,
                           self.look_s[1] + (self.look[1] - self.look_s[1]) * a)

            # ---- 更新 (全部按 dt 积分, 与帧率无关) ----
            lx, ly = self.look_s
            if lx or ly:
                self.yaw -= lx * YAW_RATE * fdt
                self.pitch = max(-0.95, min(0.70,
                                            self.pitch - ly * PITCH_RATE * fdt))
            if self.keys["dig"] or self.keys["put"]:
                tgt = self.pick()
                if tgt:
                    ix, iy, ih = tgt
                    idx = iy * MAP_SIZE + ix
                    # ★ 一次正好加/减一级台阶(QUANT) —— 加 30 这种"半级"会
                    #   变成一根 1 格宽的细高墙, 看着就是"一条线"
                    if self.keys["dig"]:
                        self.hm[idx] = max(1, ih - QUANT)
                        self.mat[idx] = 0            # 挖掉 -> 恢复自动材质
                        self.msg = "挖掉了一块"
                        act = "DIG"
                    else:
                        name, band, col = MATERIALS[self.MAT_SEL]
                        self.hm[idx] = min(255, ih + QUANT)
                        self.mat[idx] = band + 1     # ★ 放的是【选中的方块】
                        self.msg = "放了一块" + name
                        act = "PUT:" + name
                    self.msg_t = 80
                    # 只重烘焙改动点周围一小块的颜色表, 不整张重算
                    self.lib.mc_rebake(ix, iy, 3)
                    # ★ 写一行操作日志 —— 用来客观验证"触摸按键真的生效"
                    try:
                        with open("/tmp/mc_act", "w") as fh:
                            fh.write("%s cell=(%d,%d) h=%d->%d mat=%d "
                                     "cam=(%.0f,%.0f,%.0f) pitch=%.2f\n"
                                     % (act, ix, iy, ih, self.hm[idx],
                                        self.mat[idx], self.x, self.y, self.z,
                                        self.pitch))
                    except Exception:
                        pass
            mx, my = self.mv_s
            if mx or my:
                gx, gy = math.sin(self.yaw), math.cos(self.yaw)
                rx, ry = math.cos(self.yaw), -math.sin(self.yaw)
                self.x += (gx * (-my) + rx * mx) * SPEED * fdt
                self.y += (gy * (-my) + ry * mx) * SPEED * fdt
            if self.keys["up"]:
                self.z += VSPEED * fdt
                self.fly = True
            if self.keys["dn"]:
                self.z -= VSPEED * fdt
                self.fly = True
            self.x %= MAP_SIZE
            self.y %= MAP_SIZE
            self.z = max(2.0, min(900.0, self.z))
            # 地面: 【平滑】跟随, 绝不瞬间吸附 —— 以前瞬间吸附会让整个画面
            # 跟着地面一起跳, 就是"上下颠簸"的来源。上升快、下降慢(有点重力感)
            gh = float(self.hm[(int(self.y) & MAP_MASK) * MAP_SIZE
                               + (int(self.x) & MAP_MASK)])
            if self.fly:
                floor = gh + 3.0
            else:
                floor = gh + EYE
                if self.z > floor + 2.0:
                    self.z += (floor - self.z) * min(1.0, 5.0 * fdt)
            if self.z < floor:
                self.z += (floor - self.z) * min(1.0, 11.0 * fdt)
            if self.msg_t > 0:
                self.msg_t -= 1

            # ---- 绘制 ----
            # ★ 每帧把准星指着的方块告诉渲染器, 让它高亮 —— 没有这个,
            #   玩家根本不知道自己要挖/放哪一块, "放一块"看起来就是凭空变化
            aim = self.aim_raw()
            if aim:
                self.lib.mc_set_highlight(aim[0], aim[1])
            else:
                self.lib.mc_set_highlight(-1, -1)
            self.aim = aim

            self.lib.mc_set_water(1)
            self.lib.mc_set_phase(frame * 2)
            # ★ 双缓冲: 这一帧画在【背面页】, 全部画完再翻过去显示。
            #   直接画在正在显示的那一页会有撕裂 —— C 渲染 29ms 逐列写,
            #   LCD 60Hz 同时在扫同一块内存, 相机一动就满屏颤抖。
            back = scr.back_page()
            scr.yoff = back
            t_a = time.time()
            self.lib.mc_render_bgr(
                ctypes.c_void_p(self.fbp + back * self.fbstride), self.fbstride,
                self.x, self.y, self.z, self.yaw, self.pitch, MAXD)
            t_b = time.time()
            # HUD 全是【直接写显存】, 不走 PIL 的 crop/convert
            scr.blit_raw(0, 0, W, self.BAR_H, self.bar_raw)
            self.dup += 1
            if self.info_raw is None or self.dup >= 3:
                self.dup = 0
                self._draw_info()
            scr.blit_raw(self.INFO_XY[0], self.INFO_XY[1],
                         self.INFO_WH[0], self.INFO_WH[1], self.info_raw)
            if self.msg_t > 0:
                if self._msg_shown != self.msg:
                    self._draw_msg()
                    self._msg_shown = self.msg
                if self.msg_raw:
                    scr.blit_raw(W - 16 - self.MSG_WH[0], self.INFO_XY[1],
                                 self.MSG_WH[0], self.MSG_WH[1], self.msg_raw)
            elif self._msg_shown is not None:
                self._msg_shown = None      # 下一条消息重新画
            scr.blit_raw(self.CTRL_X, self.CTRL_Y, 260, 184, self.ctrl_raw)
            scr.blit_raw(self.MATBAR_XY[0], self.MATBAR_XY[1],
                         self.MATBAR_WH[0], self.MATBAR_WH[1], self.matbar_raw)
            # (准星由 C 直接画在 framebuffer 上, Python 不碰)
            scr.pan(back)                          # ★ 整页画完再翻过去
            t_d = time.time()
            self.t_r = (t_b - t_a) * 1000.0        # C 渲染
            self.t_draw = (t_d - t_b) * 1000.0     # HUD 推送

            frame += 1
            if frame % 15 == 0:
                now = time.time()
                self.fps = 15.0 / max(1e-6, now - t_fps)
                t_fps = now
                try:
                    with open("/tmp/mc_fps", "w") as fh:
                        fh.write("%.1f frame=%d  C渲染=%.1fms  HUD+推送=%.1fms  "
                                 "总=%.1fms\n"
                                 % (self.fps, frame, self.t_r, self.t_draw,
                                    1000.0 / max(1e-6, self.fps)))
                except Exception:
                    pass
            dt = time.time() - t0
            if dt < 1 / 30.0:
                time.sleep(1 / 30.0 - dt)


def run(scr, touch):
    MC(scr, touch).run()
