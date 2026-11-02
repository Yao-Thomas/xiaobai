#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""renderlab.py —— 在 PC 上本地编译 + 渲染 mcrender.c, 快速看效果

用法:
    python renderlab.py            # 编译 + 渲染一组视角 -> sheet.png
    python renderlab.py --no-build # 不重新编译
    python renderlab.py world      # 只出地形俯视图 (看颜色图烘焙得对不对)
"""
import ctypes
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
sys.path.insert(0, UI)

import apps_mc          # noqa: E402  (要在 sys.path 之后)

W, H = 1024, 600
RW, RH = getattr(apps_mc, "RW", 512), getattr(apps_mc, "RH", 300)

VCVARS = (r"C:\Program Files\Microsoft Visual Studio\2022\Community"
          r"\VC\Auxiliary\Build\vcvars64.bat")
DLL = os.path.join(HERE, "mcrender_local.dll")


def build():
    src = os.path.join(HERE, "mcrender.c")
    # MSVC 的 DLL 默认不导出任何符号, 用 .def 声明 (板子上的 gcc 不需要)
    deff = os.path.join(HERE, "mcrender.def")
    for f in (DLL, os.path.join(HERE, "mcrender_local.exp"),
              os.path.join(HERE, "mcrender_local.lib")):
        if os.path.exists(f):
            os.remove(f)
    inner = ('call "{}" >nul 2>&1\n'
             'cl /nologo /utf-8 /O2 /LD /Fe:"{}" "{}" /link /DEF:"{}"\n'
             .format(VCVARS, DLL, src, deff))
    # ★ 用 .bat 包一层, 免得跟 cmd /c 的引号解析规则打架
    bat = os.path.join(HERE, "_build_local.bat")
    with open(bat, "w", encoding="gbk") as fh:
        fh.write("@echo off\r\n" + inner.replace("\n", "\r\n"))
    r = subprocess.run(["cmd", "/c", bat], capture_output=True,
                       text=True, encoding="gbk", errors="replace")
    if not os.path.exists(DLL):
        print(r.stdout, r.stderr)
        raise SystemExit("编译失败")
    print("build OK ->", DLL)


class MC:
    def __init__(self, hm, mat=None):
        self.lib = ctypes.CDLL(DLL)
        L = self.lib
        ub = ctypes.POINTER(ctypes.c_ubyte)
        L.mc_init.argtypes = [ub, ctypes.c_int]
        L.mc_setres.argtypes = [ctypes.c_int] * 4 + [ctypes.c_float]
        L.mc_set_skip.argtypes = [ctypes.c_int] * 5
        L.mc_render.argtypes = [ub] + [ctypes.c_float] * 5 + [ctypes.c_int]
        L.mc_cell.argtypes = [ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int)]
        L.mc_pal.argtypes = [ctypes.c_int] + [ctypes.POINTER(ctypes.c_int)] * 3
        L.mc_pick.argtypes = ([ctypes.c_float] * 5 + [ctypes.c_int]
                              + [ctypes.POINTER(ctypes.c_int)] * 3)
        L.mc_pick.restype = ctypes.c_int
        L.mc_rebake.argtypes = [ctypes.c_int] * 3
        L.mc_set_highlight.argtypes = [ctypes.c_int, ctypes.c_int]
        L.mc_set_water.argtypes = [ctypes.c_int]
        L.mc_set_mat.argtypes = [ub]
        self.hm = hm
        self.mat = mat
        self.buf = (ctypes.c_ubyte * len(hm)).from_buffer(hm)
        L.mc_init(self.buf, 9)
        if mat is not None:
            self.matbuf = (ctypes.c_ubyte * len(mat)).from_buffer(mat)
            L.mc_set_mat(self.matbuf)
        L.mc_setres(RW, RH, W, H, getattr(apps_mc, "FOCAL", 256.0))
        L.mc_set_hscale.argtypes = [ctypes.c_float]
        L.mc_set_hscale(getattr(apps_mc, "HSCALE", 0.42))
        L.mc_set_edge.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_int]
        L.mc_set_edge(1, 0.70, 6)
        L.mc_set_skip(0, 0, 0, 0, 0)
        self.out = (ctypes.c_ubyte * (W * H * 3))()

    def render(self, x, y, z, yaw, pitch, maxd=280):
        self.lib.mc_render(self.out, x, y, z, yaw, pitch, maxd)
        return Image.frombytes("RGB", (W, H), bytes(self.out))

    def cell(self, x, y):
        h = ctypes.c_int(0)
        c = ctypes.c_int(0)
        self.lib.mc_cell(x, y, ctypes.byref(h), ctypes.byref(c))
        return h.value, c.value

    def pal(self, i):
        r, g, b = (ctypes.c_int(0) for _ in range(3))
        self.lib.mc_pal(i, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b))
        return (r.value, g.value, b.value)

    def pick(self, x, y, z, yaw, pitch, maxd=280):
        ox, oy, oz = (ctypes.c_int(0) for _ in range(3))
        r = self.lib.mc_pick(x, y, z, yaw, pitch, maxd,
                             ctypes.byref(ox), ctypes.byref(oy), ctypes.byref(oz))
        return (ox.value, oy.value, oz.value) if r == 0 else None

    def place(self, ix, iy, dz):
        idx = (iy & 511) * 512 + (ix & 511)
        self.hm[idx] = max(1, min(255, self.hm[idx] + dz))
        self.lib.mc_rebake(ix, iy, 3)
        return self.hm[idx]


def grad_stats(hm, size=512, step=2):
    s = n = mx = 0
    for y in range(0, size, step):
        r = y * size
        for x in range(0, size - 1, step):
            d = abs(hm[r + x + 1] - hm[r + x])
            s += d
            n += 1
            if d > mx:
                mx = d
    return s / float(n), mx


def histogram(hm, size=512):
    h = [0] * 256
    for v in hm:
        h[v] += 1
    return [x / float(size * size) for x in h]


def percentiles(hm):
    vals = sorted(hm)
    n = len(vals)
    out = {}
    for p in (1, 2, 5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95, 98, 99):
        out[p] = vals[min(n - 1, int(n * p / 100.0))]
    return out


def world_preview(mc, size=512, out="world.png"):
    im = Image.new("RGB", (size, size))
    px = im.load()
    pal = [mc.pal(i) for i in range(256)]
    for y in range(size):
        for x in range(size):
            h, c = mc.cell(x, y)
            px[x, y] = pal[c]
    im = im.resize((size * 2, size * 2), Image.NEAREST)
    im.save(out)
    print("world preview ->", out)
    return im


def main():
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("--")]
    if "--no-build" not in args:
        build()
    if not os.path.exists(DLL):
        raise SystemExit("没有 dll, 先跑一次完整编译")

    import apps_mc
    hm = apps_mc.make_heightmap(quant=getattr(apps_mc, "QUANT", 0))
    mat = bytearray(len(hm))
    nt = apps_mc.make_trees(hm, mat)
    print("种了 %d 棵树" % nt)
    ga, gm = grad_stats(hm)
    hist = histogram(hm)
    lo = next(i for i, v in enumerate(hist) if v > 0.001)
    hi = 255 - next(i for i, v in enumerate(reversed(hist)) if v > 0.001)
    print("高度: 范围 %d..%d  均值 %.1f" % (lo, hi, sum(hm) / len(hm)))
    print("坡度: 相邻格平均 |dh| = %.2f  最大 = %d   (官方地图约 0.25)" % (ga, gm))
    lo60 = sum(hist[:56]) * 100
    hi215 = sum(hist[215:]) * 100
    print("水面占比 %.1f%%   雪山占比 %.1f%%" % (lo60, hi215))
    pc = percentiles(hm)
    print("高度分位数: " + "  ".join("%d%%=%d" % (k, pc[k])
                                     for k in (1, 5, 10, 25, 50, 75, 90, 95, 99)))

    mc = MC(hm, mat)
    if pos and pos[0] == "world":
        world_preview(mc)
        return

    # 找一个草地出生点(和 apps_mc 一样的逻辑)
    import random
    random.seed(1)
    bx = by = 256
    best = 1e9
    for _ in range(3000):
        tx = random.randrange(512)
        ty = random.randrange(512)
        d = abs(hm[ty * 512 + tx] - 95)
        if d < best:
            best, bx, by = d, tx, ty
    gh = hm[by * 512 + bx]
    print("出生点 (%d,%d) 地面高 %d" % (bx, by, gh))
    z = gh + getattr(apps_mc, "EYE", 26.0)

    if pos and pos[0] == "sweep":
        # ★ 立方体方块的条件 (几何):
        #   方块宽 = 1 格(世界单位), 方块高 = QUANT*HSCALE (视觉单位)
        #   要像立方体 -> QUANT*HSCALE ≈ 1  ->  HSCALE = 1/QUANT
        #   要第一人称 -> 眼高 EYE*HSCALE ≈ 3 个方块
        #   地形视觉坡度 = |dh|*HSCALE, 要远小于 1, 否则抬头就是墙
        q_list = [2, 4, 8]
        cw, ch = W // 3, H // 3
        sheet = Image.new("RGB", (cw * len(q_list), ch * len(q_list) + 20),
                          (20, 20, 24))
        d = ImageDraw.Draw(sheet)
        for r, q in enumerate(q_list):
            hm2 = apps_mc.make_heightmap(quant=q)
            m2 = MC(hm2)
            hs = 1.0 / q
            m2.lib.mc_set_hscale(hs)
            m2.lib.mc_setres(RW, RH, W, H, 300.0)
            g2 = hm2[by * 512 + bx]
            ga2, gm2 = grad_stats(hm2)
            for c, eyeq in enumerate(q_list):
                eye = eyeq * 3.0
                im = m2.render(bx, by, g2 + eye, 0.0, -0.12, 260)
                im = im.resize((cw, ch), Image.LANCZOS)
                sheet.paste(im, (c * cw, r * ch + 20))
                d.text((c * cw + 4, r * ch + 4),
                       "quant=%d eye=%g hs=%.3f 视坡度=%.2f 最大=%d"
                       % (q, eye, hs, ga2 * hs, gm2), fill=(255, 255, 0))
        sheet.save("sweep.png")
        print("sweep -> sweep.png")
        return

    if pos and pos[0] == "place":
        # 验证"放一块"到底是不是一个方块 —— 准星指着哪、放完长什么样
        q = getattr(apps_mc, "QUANT", 24)
        m2 = MC(apps_mc.make_heightmap(quant=q))
        g2 = m2.hm[by * 512 + bx]
        cz = g2 + getattr(apps_mc, "EYE", 30.0)
        pitch = -0.30
        tgt = m2.pick(bx, by, cz, 0.0, pitch, getattr(apps_mc, "MAXD", 180))
        print("出生点(%d,%d) 地面高 %d  相机高 %.0f" % (bx, by, g2, cz))
        print("准星拾取 ->", tgt, " (QUANT=%d)" % q)
        before = m2.render(bx, by, cz, 0.0, pitch, getattr(apps_mc, "MAXD", 180))
        after = before
        if tgt:
            nh = m2.place(tgt[0], tgt[1], q)
            print("放置后该格高度 %d -> %d" % (tgt[2], nh))
            after = m2.render(bx, by, cz, 0.0, pitch, getattr(apps_mc, "MAXD", 180))
        sheet = Image.new("RGB", (W, H + 20), (20, 20, 24))
        d = ImageDraw.Draw(sheet)
        sheet.paste(before.resize((W // 2, H // 2)), (0, 20))
        sheet.paste(after.resize((W // 2, H // 2)), (W // 2, 20))
        d.text((4, 4), "BEFORE  pick=%s" % (tgt,), fill=(255, 255, 0))
        d.text((W // 2 + 4, 4), "AFTER place +%d" % q, fill=(0, 255, 120))
        sheet.save("place.png")
        print("place -> place.png")
        return

    if pos and pos[0] == "cam":
        # 用指定相机复现板子上的一帧:  python renderlab.py cam X Y YAW PITCH ALT
        cx = float(pos[1]); cy = float(pos[2])
        yaw = float(pos[3]); pitch = float(pos[4]); alt = float(pos[5])
        gh = hm[int(cy) * 512 + int(cx)]
        m2 = MC(hm, mat)
        m2.lib.mc_setres(RW, RH, W, H, getattr(apps_mc, "FOCAL", 600.0))
        m2.lib.mc_set_hscale(getattr(apps_mc, "HSCALE", 0.125))
        m2.lib.mc_set_edge(1, 0.78, 12)
        MAXD2 = getattr(apps_mc, "MAXD", 200)
        im = m2.render(cx, cy, gh + alt, yaw, pitch, MAXD2)
        im.save("cam.png")
        print("cam -> cam.png  地面高 %d  z=%.1f  方向向量 fx=%.3f fy=%.3f"
              % (gh, gh + alt, __import__("math").sin(yaw), __import__("math").cos(yaw)))
        px = im.load()
        sky = px[1000, 120]
        blank = 0
        tot = 0
        for xx in range(0, W, 8):
            tot += 1
            has = False
            for yy in range(150, 600, 6):
                c = px[xx, yy]
                if abs(c[0] - sky[0]) + abs(c[1] - sky[1]) + abs(c[2] - sky[2]) > 30:
                    has = True
                    break
            if not has:
                blank += 1
        print("  空列占比 %.0f%% (采样 %d 列)" % (blank * 100.0 / tot, tot))
        return

    if pos and pos[0] == "board":
        # 完全复刻板子的地形数据: 同一 seed -> 同一出生点 -> 同一批树
        import random as _r
        hm2 = apps_mc.make_heightmap(quant=getattr(apps_mc, "QUANT", 8))
        mat2 = bytearray(len(hm2))
        # 复刻 _find_spawn (它用的是全局 random, 状态承接 make_heightmap)
        best, bx2, by2 = 1e9, 256, 256
        for _ in range(4000):
            tx = _r.randrange(512); ty = _r.randrange(512)
            h = hm2[ty * 512 + tx]
            cost = abs(h - 95) * 3.0
            for r in (6, 10, 14):
                for k in range(-r, r + 1, max(1, r // 3)):
                    for (dx, dy) in ((k, -r), (k, r), (-r, k), (r, k)):
                        hh = hm2[((ty + dy) & 511) * 512 + ((tx + dx) & 511)]
                        if hh > h:
                            cost += (hh - h) * 0.35
            if cost < best:
                best, bx2, by2 = cost, tx, ty
                if cost < 4:
                    break
        nt = apps_mc.make_trees(hm2, mat2, avoid=(bx2, by2))
        print("复刻: 出生点 (%d,%d) 代价 %.1f  种树 %d 棵" % (bx2, by2, best, nt))
        print("hm 校验: sum=%d  len=%d  mat非零=%d"
              % (sum(hm2), len(hm2), sum(1 for v in mat2 if v)))
        print("hm[0:8] =", list(hm2[:8]))
        m3 = MC(hm2, mat2)
        m3.lib.mc_setres(RW, RH, W, H, getattr(apps_mc, "FOCAL", 600.0))
        m3.lib.mc_set_hscale(getattr(apps_mc, "HSCALE", 0.125))
        m3.lib.mc_set_edge(1, 0.78, 12)
        gh3 = hm2[by2 * 512 + bx2]
        im = m3.render(bx2, by2, gh3 + getattr(apps_mc, "EYE", 22), 0.0, -0.30,
                       getattr(apps_mc, "MAXD", 200))
        im.save("board_sim.png")
        px = im.load()
        sky = px[1000, 120]
        blank = tot = 0
        for xx in range(0, W, 8):
            tot += 1
            has = any(abs(px[xx, yy][0] - sky[0]) + abs(px[xx, yy][1] - sky[1])
                      + abs(px[xx, yy][2] - sky[2]) > 30
                      for yy in range(150, 600, 6))
            if not has:
                blank += 1
        print("board_sim -> board_sim.png  空列 %.0f%%" % (blank * 100.0 / tot))
        return

    views = [
        ("fwd",       bx, by, z, 0.0, -0.10),
        ("fwd_up",    bx, by, z, 0.0, 0.10),
        ("fwd_down",  bx, by, z, 0.0, -0.35),
        ("rot90",     bx, by, z, 1.5708, -0.10),
        ("rot180",    bx, by, z, 3.1416, -0.10),
        ("high",      bx, by, gh + 90, 0.0, -0.35),
    ]
    sheet = Image.new("RGB", (W // 2 * 3, H // 2 * 2 + 40), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    for i, (name, x, y, zz, yaw, pitch) in enumerate(views):
        im = mc.render(x, y, zz, yaw, pitch).resize((W // 2, H // 2), Image.LANCZOS)
        cx = (i % 3) * (W // 2)
        cy = (i // 3) * (H // 2 + 20) + 20
        sheet.paste(im, (cx, cy))
        d.text((cx + 4, cy - 15), "%s yaw=%.2f pitch=%.2f z=%.0f" % (name, yaw, pitch, zz),
               fill=(255, 255, 255))
    sheet.save("sheet.png")
    print("contact sheet -> sheet.png")
    # 单独存一张全尺寸
    mc.render(bx, by, z, 0.0, -0.10).save("view_fwd.png")
    world_preview(mc)


main()
