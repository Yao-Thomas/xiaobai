#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fbui.py —— Zynq 板载 7 寸屏(1024x600 24bpp) 图形库
  用 PIL 画图 -> 转 RGB -> 直接写 /dev/fb0
  触摸用 evdev 读 GT911

★★★ 2026-10-03 修正像素字节序（重要！）
────────────────────────────────────────────────────────────────────
原来这里写的是 "BGR;24"（PIL 会输出 B,G,R 字节序）。
但实测板子的 VTC/framebuffer 是按【标准 RGB】解释字节的，
⇒ 整个板载 UI 的红蓝一直是反的（深蓝背景显示成棕红）。

怎么测出来的（/home/zynq/color_probe.py）：
    往屏幕写三块纯色，按【标准 RGB】顺序： (255,0,0) (0,255,0) (0,0,255)
    人眼看屏幕 → 红 绿 蓝   ← 顺序正确
    ⇒ 面板就是 RGB，之前的 "BGR;24" 是错的

影响面：这个文件是【整个板载 UI 的地基】（桌面 / 所有 App / 示波器界面），
        所以这个 bug 让全板的颜色都是互换的，只是深色主题下大部分是灰色，
        不容易察觉 —— 直到看到明显的蓝色元素变成棕红才暴露出来。
────────────────────────────────────────────────────────────────────
"""
import os, sys, mmap, struct, time, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W_, H_ = 1024, 600

def rd(p, d=None):
    try:
        return open(p).read().strip()
    except Exception:
        return d

# ---------------- 字体 ----------------
_DEJAVU_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_DEJAVU_B_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_MONO_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
]
_CN_PATHS = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",   # 板子上(文泉驿)
    "C:/Windows/Fonts/msyh.ttc",                       # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",                     # 黑体
    "C:/Windows/Fonts/simsun.ttc",                     # 宋体
]
_fc = {}
_TWC = {}          # 文字宽度缓存 (tw) —— 见 Screen.tw 的说明
_MC = {}           # 字体度量缓存 (getmetrics) —— 老 Pillow 的 getmetrics 内部
                   # 居然走 getsize，上板实测一帧被调 291 次、白花 20ms


def _load(paths, size):
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def font(size, bold=False, cn=False, mono=False):
    k = (size, bold, cn, mono)
    if k not in _fc:
        if cn:
            _fc[k] = _load(_CN_PATHS, size)
        elif mono:
            _fc[k] = _load(_MONO_PATHS, size)
        else:
            _fc[k] = _load(_DEJAVU_B_PATHS if bold else _DEJAVU_PATHS, size)
    return _fc[k]



# ══════════════════════════════════════════════════════════════════════
#  ★★★ 壁纸调暖（2026-10-03）
# ══════════════════════════════════════════════════════════════════════
# 用户要"整体背景回到原先的暖棕红观感"，但桌面最大的视觉面积是【壁纸】，
# 而壁纸是一张图片（scrimg.paste 贴上去的），改调色板常量根本碰不到它。
#
# 所以单独给壁纸加一个暖色处理：把蓝通道压下来、红通道提一点。
# ★ 只作用于壁纸，【不影响图标和软件的颜色】—— 这正是用户的要求
#   （"除了软件及其图标"）。
#
# ★ 原则（一定要分清，不然会双重处理）：
#     资源图（壁纸、从文件加载的图片）  -> warm_image() 调暖
#     屏幕缓存（scr.img.copy() 存的）  -> 已经是调暖后的，不要再处理
# ══════════════════════════════════════════════════════════════════════
WARM_B_DROP = 30      # 蓝通道压低多少
WARM_R_ADD = 14       # 红通道提高多少


def warm_image(im, b_drop=None, r_add=None):
    """把一张【资源图】调暖（降蓝、提红）。只用于壁纸这类背景图。"""
    b_drop = WARM_B_DROP if b_drop is None else b_drop
    r_add = WARM_R_ADD if r_add is None else r_add
    if b_drop == 0 and r_add == 0:
        return im
    if im.mode != "RGB":
        im = im.convert("RGB")
    r, g, b = im.split()
    r = r.point([min(255, v + r_add) for v in range(256)])
    b = b.point([max(0, v - b_drop) for v in range(256)])
    return Image.merge("RGB", (r, g, b))


# ---------------- 屏幕 ----------------

# ══════════════════════════════════════════════════════════════════════
#  ★★★ 模块级色温补偿（给"资源图"用）
# ══════════════════════════════════════════════════════════════════════
# 为什么需要模块级：
#   壁纸、从文件加载的图片、PIL 直接生成的图 —— 这些都不经过 scr.d
#   （ColorDraw 代理），所以在 Screen 里做补偿对它们无效。
#
#   最干净的修法不是"每个 paste 处都改"，而是【在资源加载的时候补一次】：
#       wall = fbui.comp_image(Image.open(path).convert("RGB"))
#   这样 self.wall 本身就是补偿过的，后面所有 paste 一个字都不用改。
#
#   ★ 区分原则（很重要，不然会双重补偿）：
#       · 资源图（文件加载 / PIL 生成）      -> 需要补偿
#       · 屏幕缓存（scr.img.copy() 存下来的）-> 已经补偿过，不要再补
# ══════════════════════════════════════════════════════════════════════
_COMP_TABLES = {"r": None, "g": None, "b": None}


def set_comp_tables(rt, gt, bt):
    """Screen.__init__ 调这个，把补偿表同步到模块级"""
    _COMP_TABLES["r"] = rt
    _COMP_TABLES["g"] = gt
    _COMP_TABLES["b"] = bt


def comp_image(im):
    """对一张【资源图】做色温补偿（没启用补偿时原样返回）"""
    rt, gt, bt = _COMP_TABLES["r"], _COMP_TABLES["g"], _COMP_TABLES["b"]
    if rt is None and gt is None and bt is None:
        return im
    if im.mode == "RGBA":
        r, g, b, a = im.split()
        if rt:
            r = r.point(rt)
        if gt:
            g = g.point(gt)
        if bt:
            b = b.point(bt)
        return Image.merge("RGBA", (r, g, b, a))
    if im.mode != "RGB":
        im = im.convert("RGB")
    if rt is None:
        rt = list(range(256))
    if gt is None:
        gt = list(range(256))
    if bt is None:
        bt = list(range(256))
    lut = rt + gt + bt
    return im.point(lut)


class ColorDraw(object):
    """★ 色温补偿代理：包住 ImageDraw，把颜色参数在【绘制时】变换掉

    ★★★ 为什么要有这个东西（三轮才对）
    ────────────────────────────────────────────────────────────────
    要给面板偏蓝做补偿。补偿本身是"逐通道的点运算"，也就是
        R' = f(R),  G' = g(G),  B' = h(B)
    这种运算有一个重要性质：★ 先画后变换 == 先变换后画 ★

    于是有两条路：
      A. 先画后变换：每帧画完整图，再对 1.8MB 像素做一遍查表
         → 实测 +25ms(point) 甚至 +41ms(切片translate)，帧率腰斩
      B. ★ 先变换后画：在把颜色【传给绘图函数】的那一刻变换
         → 每个绘图调用只算一次颜色，而不是每个像素算一次
         → 开销几乎为 0

    这个类走 B。它拦下所有 fill / outline 参数，
    过一遍 comp_color() 再交给真正的 ImageDraw。

    ★ 因为色数远少于像素数（一帧可能几百次绘图调用，几十万像素），
      这是数量级的差别。
    ────────────────────────────────────────────────────────────────
    """

    # 这些方法参数里颜色可能出现的位置（fill/outline 都是关键字参数）
    COLOR_KW = ("fill", "outline", "background")

    def __init__(self, draw, screen):
        self._d = draw
        self._s = screen

    def __getattr__(self, name):
        fn = getattr(self._d, name)
        if not callable(fn):
            return fn
        scr = self._s

        def wrapper(*a, **kw):
            for k in ColorDraw.COLOR_KW:
                if k in kw and kw[k] is not None:
                    kw[k] = scr.comp_color(kw[k])
            return fn(*a, **kw)
        return wrapper

    # ---- 常用的直通方法（避免每次走 __getattr__）----
    #
    # ★★★ 踩坑：这些包装方法的签名必须和 PIL 的【完全一致】，
    #   多传一个参数就会 TypeError。我第一次给 polygon 加了 width=，
    #   而 PIL 的 ImageDraw.polygon(xy, fill, outline) 根本没有 width
    #   ⇒ 桌面一画播放按钮就崩（TypeError），连崩三次。
    #
    #   PIL 各方法的真实签名（与本文件其余代码实际用到的对齐）：
    #     line(xy, fill=None, width=0, joint=None)
    #     rectangle(xy, fill=None, outline=None, width=1)
    #     ellipse(xy, fill=None, outline=None, width=1)
    #     polygon(xy, fill=None, outline=None)          ← ★ 没有 width
    #     arc(xy, start, end, fill=None, width=1)
    def line(self, xy, fill=None, width=0, joint=None):
        return self._d.line(xy, fill=self._s.comp_color(fill), width=width,
                            joint=joint)

    def rectangle(self, xy, fill=None, outline=None, width=1):
        return self._d.rectangle(xy, fill=self._s.comp_color(fill),
                                 outline=self._s.comp_color(outline),
                                 width=width)

    def ellipse(self, xy, fill=None, outline=None, width=1):
        return self._d.ellipse(xy, fill=self._s.comp_color(fill),
                               outline=self._s.comp_color(outline),
                               width=width)

    def polygon(self, xy, fill=None, outline=None):
        # ★ 不要加 width —— PIL 的 polygon 没有这个参数
        return self._d.polygon(xy, fill=self._s.comp_color(fill),
                               outline=self._s.comp_color(outline))

    def arc(self, xy, start, end, fill=None, width=1):
        return self._d.arc(xy, start, end,
                           fill=self._s.comp_color(fill), width=width)


class Screen:
    def __init__(self):
        vs = rd("/sys/class/graphics/fb0/virtual_size", "1024,1200").split(",")
        self.vh = int(vs[1])
        self.w, self.h = int(vs[0]), min(600, int(vs[1]))
        self.bpp = int(rd("/sys/class/graphics/fb0/bits_per_pixel", "24"))
        self.bppx = self.bpp // 8
        self.stride = int(rd("/sys/class/graphics/fb0/stride", str(self.w * self.bppx)))
        self.f = open("/dev/fb0", "r+b")
        self.mm = mmap.mmap(self.f.fileno(), self.stride * self.vh,
                            mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.img = Image.new("RGB", (self.w, self.h), (12, 16, 32))
        self.d = ColorDraw(ImageDraw.Draw(self.img), self)
        # ★★★ 像素字节序：★★ 必须是 "RGB" / "RGBA" ★★
        #
        # 原来写的是 "BGR;24" / "BGRA"（PIL 会让 tobytes() 输出 B,G,R 顺序），
        # 但实测面板是按【标准 RGB】解释字节的 —— 于是颜色红蓝互换：
        #     设计深蓝 (10,12,22)  → 显示成棕红 (22,12,10)
        #     设计按钮 (52,70,120) → 显示成棕红 (120,70,52)
        #
        # 已用 /home/zynq/color_probe.py 验证：按 RGB 顺序写三块纯色，
        # 屏幕上就是 红/绿/蓝，顺序正确 ⇒ 面板是 RGB。
        #
        # ★ 别再改回 BGR 了。要换屏或者换面板再实测一遍。
        self.mode = {24: "RGB", 32: "RGBA"}.get(self.bpp, "RGB")

        # ══════════════════════════════════════════════════════════════
        #  ★★★ 面板色温补偿 —— 【已关闭】（2026-10-03）
        # ══════════════════════════════════════════════════════════════
        # 背景：修好字节序（BGR;24 → RGB）后颜色终于正确，但用户觉得
        #       "整体背景变太蓝了"。查下来是【面板本身色温偏冷】：
        #       中性灰 (18,18,18) 在屏上显示成蓝色，8 级中性灰全偏蓝
        #       （用 calib_pattern.py 受控标定 + temp_calib.py 人眼标定确认）。
        #
        # 做过补偿：蓝通道 增益 0.99、偏置 -12（用户标定答"中间"算出来的）。
        # 实现方式最终选的是【绘制时变换颜色】（ColorDraw 代理 +
        # comp_image 给资源图），开销≈0；每帧后处理要 +25~41ms，被否掉。
        #
        # ★ 但用户最终判断："一点没变…算了是硬件问题，你别管了"，
        #   要求全部改回原先配色。
        #   ⇒ 这里把补偿置为【恒等】，所有颜色回到原始设计值。
        #
        # ★ 下面这套机制（ColorDraw / comp_image / _build_lut）保留着，
        #   因为它们【恒等时开销为 0】（_ident=True 直接返回），
        #   将来真要调色温，把这两个数改一下就行，不用重新写代码。
        # ══════════════════════════════════════════════════════════════
        self.COMP_B = 0           # 蓝通道偏置（0 = 不补偿）
        self.COMP_B_GAIN = 1.0    # 蓝通道增益（1.0 = 不补偿）
        self.COMP_R = 0
        self.COMP_G = 0
        self._lut = None          # 缓存查表
        self._build_lut()

        self._fast = (self.stride == self.w * self.bppx)
        # ★ 双缓冲: yres_virtual=1200 说明有第二页可用。
        #   以前一直画在【正在显示】的那一页 —— C 渲染要 29ms 逐列写 1.8MB,
        #   而 LCD 在 60Hz 不停地扫同一块内存, 渲染到一半屏幕已经在读了,
        #   于是画面撕裂: 相机一动就满屏颤抖、亮的地方闪白。
        #   yoff = 这一帧画到哪一页(行偏移), pan() 负责翻页。
        self.PANFILE = "/sys/class/graphics/fb0/pan"
        self.page_h = self.h
        self.yoff = 0
        try:
            self.yoff = int(rd(self.PANFILE, "0,0").split(",")[1])
        except Exception:
            self.yoff = 0
        self.phys = self._fb_phys()          # 显存物理地址(GPU 用)
        self.gpu = None                      # 可选: FPGA GPU 加速器
        print("fb: %dx%d (virt %d) %dbpp stride=%d %s phys=0x%08X" %
              (self.w, self.h, self.vh, self.bpp, self.stride,
               "快速路径" if self._fast else "逐行路径", self.phys or 0))
        print("色彩补偿: 蓝 增益%.3f 偏置%+d  红偏置%+d  绿偏置%+d"
              % (self.COMP_B_GAIN, -self.COMP_B, self.COMP_R, self.COMP_G))

    # ══════════════════════════════════════════════════════════════════
    #  面板色温补偿 LUT
    # ══════════════════════════════════════════════════════════════════
    def _build_lut(self):
        """建查表：只用于 __getattr__ 兜底的单点变换

        ★★★ 性能踩坑记录（三轮才对，值得记下来）
        ────────────────────────────────────────────────────────────
        需求：补偿面板偏蓝。第一反应是"画完再做整图后处理"。

          第 1 版  img.point(lut)          flush 37→63ms  (+25ms)
          第 2 版  ba[2::3].translate(tb)  flush 38→79ms  (+41ms!)
                   —— Python 层切片赋值要做三次 1.8MB 拷贝，比 point 还糟
          单独基准测下来 translate 只 +5.4ms，但进了 flush 就变成 +41ms
          （flush 里还有 convert，两段大内存操作叠在一起，cache 全miss）

        结论：★ 每帧对整图做后处理这条路根本不该走 ★

        第 3 版（现在这版）：补偿是【逐通道的点运算】，
            那就在【传给绘图函数的时候】把颜色变换掉 ——
            每个绘图调用只算一次，而不是每个像素算一次。
            开销从 "25~41 ms/帧" 降到 "几乎为 0"。

        实现：ColorDraw 代理包住 ImageDraw，拦截所有 fill/outline 参数。
        ────────────────────────────────────────────────────────────
        """
        def bch(v):
            x = int(v * self.COMP_B_GAIN) - self.COMP_B
            return 0 if x < 0 else (255 if x > 255 else x)

        def rch(v):
            x = v + self.COMP_R
            return 0 if x < 0 else (255 if x > 255 else x)

        def gch(v):
            x = v + self.COMP_G
            return 0 if x < 0 else (255 if x > 255 else x)

        self._ident = (self.COMP_B == 0 and self.COMP_B_GAIN >= 0.9999
                       and self.COMP_R == 0 and self.COMP_G == 0)
        self._lut = None
        if self._ident:
            self._rt = self._gt = self._bt = None
            set_comp_tables(None, None, None)     # ★ 同步到模块级
            return
        self._rt = [rch(v) for v in range(256)]
        self._gt = [gch(v) for v in range(256)]
        self._bt = [bch(v) for v in range(256)]
        # ★ 同步到模块级 —— 好让 comp_image() 能给资源图（壁纸等）做补偿
        set_comp_tables(self._rt, self._gt, self._bt)

    def comp_color(self, col):
        """把一个颜色过一遍色温补偿（RGB 三元组或整数都行）"""
        if getattr(self, "_ident", True) or col is None:
            return col
        if isinstance(col, int):
            r = (col >> 16) & 255
            g = (col >> 8) & 255
            b = col & 255
            return (self._rt[r] << 16) | (self._gt[g] << 8) | self._bt[b]
        try:
            r, g, b = col[0], col[1], col[2]
        except Exception:
            return col
        out = (self._rt[r], self._gt[g], self._bt[b])
        return out + tuple(col[3:]) if len(col) > 3 else out

    def _fb_phys(self):
        """取显存物理地址
        1) 先试 FBIOGET_FSCREENINFO 的 smem_start
        2) DRM 的 fbdev 模拟会返回 0 -> 退回读 /home/zynq/.fb_phys
           (该文件由 find_fb_phys.py 用"写图案+搜物理内存"的方法生成)
        """
        import ctypes, fcntl
        class FBFix(ctypes.Structure):
            _fields_ = [("id", ctypes.c_char * 16),
                        ("smem_start", ctypes.c_ulong),
                        ("smem_len", ctypes.c_uint32),
                        ("type", ctypes.c_uint32),
                        ("type_aux", ctypes.c_uint32),
                        ("visual", ctypes.c_uint32),
                        ("xpanstep", ctypes.c_uint16),
                        ("ypanstep", ctypes.c_uint16),
                        ("ywrapstep", ctypes.c_uint16),
                        ("__pad", ctypes.c_uint16),
                        ("line_length", ctypes.c_uint32)]
        try:
            fix = FBFix()
            fcntl.ioctl(self.f.fileno(), 0x4602, fix)
            if fix.smem_start:
                return fix.smem_start
        except Exception:
            pass
        # 退回物理地址缓存文件
        for p in ("/home/zynq/.fb_phys",):
            try:
                v = int(open(p).read().strip(), 0)
                if v:
                    return v
            except Exception:
                pass
        return 0

    def attach_gpu(self, gpu):
        """挂上 FPGA GPU; 之后 fill() 会走硬件"""
        self.gpu = gpu
        print("已挂载 FPGA GPU 加速 ✅")

    # ---- 双缓冲翻页 ----
    def pan(self, y):
        """把显示切到行偏移 y 那一页, 并记下这一页是当前页"""
        y = int(y)
        try:
            with open(self.PANFILE, "w") as f:
                f.write("0,%d" % y)
        except Exception:
            pass
        self.yoff = y

    def back_page(self):
        """返回"另一页"的行偏移(和当前显示页不同)"""
        return 0 if self.yoff else self.page_h

    def fill(self, x, y, w, h, color):
        """填充矩形: 有 GPU 走硬件, 否则走 PIL"""
        if self.gpu is not None and self.phys:
            try:
                self.gpu.fill(self.phys, self.stride, x, y, w, h, color & 0xFFFFFF)
                self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=color)
                return True
            except Exception as ex:
                print("GPU 填充失败, 回退软件:", ex)
                self.gpu = None
        self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=color)
        return False

    def flush(self, box=None):
        """把 PIL 图像推到屏幕; box=(x0,y0,x1,y1) 只推局部

        ★ 色温补偿【不在这里做】—— 在 ColorDraw 里做（绘制时就把颜色变换掉）。
          放在那里是因为它开销几乎为 0；放在这里做整图像素后处理要 +25~41ms/帧。
        """
        if box is None or not self._fast:
            if box is None:
                # ★ 颜色已经在【绘制时】补偿过了（见 ColorDraw），这里不用再处理
                raw = self.img.convert(self.mode).tobytes()
                o0 = self.yoff * self.stride
                self.mm[o0:o0 + len(raw)] = raw
                return
            x0, y0, x1, y1 = box
        else:
            x0, y0, x1, y1 = box
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.w, x1); y1 = min(self.h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        sub = self.img.crop((x0, y0, x1, y1)).convert(self.mode).tobytes()
        rowlen = (x1 - x0) * self.bppx
        yo = self.yoff * self.stride
        for y in range(y0, y1):
            o = yo + y * self.stride + x0 * self.bppx
            self.mm[o:o + rowlen] = sub[(y - y0) * rowlen:(y - y0 + 1) * rowlen]

    # ---- 快路径: 预转换 + 直接写显存 ----------------------------------
    # ★ 为什么需要这两个:
    #   flush() 每次都要 crop + convert("RGB") + tobytes(), 在板子上
    #   1024x96 的区域光转换就 4.6ms。对【每帧都不变】的 UI (信息栏背景、
    #   按钮) 完全没必要重复转换 —— 转一次存下来, 之后只做内存写。
    def to_raw(self, im):
        """把 PIL 图像预转成和显存一致的原始字节 (RGB/RGBA), 供 blit_raw 用

        ★ 一样要过色温补偿 —— 否则走快路径贴上去的图会"没补偿"，
          和 flush() 出来的颜色不一致（画面里一块偏蓝一块正常）。
        """
        return im.convert(self.mode).tobytes()

    def blit_raw(self, x0, y0, w, h, data):
        """把 to_raw() 得到的字节【不透明】直接贴进显存

        比 flush(box) 快得多: 没有 crop / convert / tobytes,
        只有 (w*bpp) 字节的 memcpy, 每行一次切片赋值。
        """
        bpp = self.bppx
        row = w * bpp
        if len(data) < row * h:
            return
        sx = x0 * bpp
        yo = self.yoff * self.stride
        for i in range(h):
            o = yo + (y0 + i) * self.stride + sx
            p = i * row
            self.mm[o:o + row] = data[p:p + row]

    def fill_raw(self, x0, y0, w, h, color):
        """把纯色矩形直接写进显存 (比 flush 一个纯色块快很多)"""
        bpp = self.bppx
        r = (color >> 16) & 255
        g = (color >> 8) & 255
        b = color & 255
        # ★ 色温补偿也要在这里做一次（这个函数绕过 PIL，直接写字节）
        if self._lut is not None:
            r = self._lut[r]              # 0..255
            g = self._lut[256 + g]
            b = self._lut[512 + b]
        # ★ 面板是 RGB（见文件头的说明），所以走 bytes((r, g, b)) 分支。
        #   保留这个三元表达式是为了万一又遇到 BGR 的面板时能快速切回去。
        px = bytes((b, g, r)) if self.mode == "BGR;24" else bytes((r, g, b))
        row = px * w
        yo = self.yoff * self.stride
        for i in range(h):
            o = yo + (y0 + i) * self.stride + x0 * bpp
            self.mm[o:o + len(row)] = row

    # ---- 绘图快捷方法 ----
    def rect(self, xy, fill=None, outline=None, width=1):
        self.d.rectangle(xy, fill=fill, outline=outline, width=width)

    def rrect(self, xy, r, fill=None, outline=None, width=1):
        """圆角矩形(PIL 7.0 没有 rounded_rectangle, 自己拼)"""
        rrect_draw(self.d, xy, r, fill=fill, outline=outline, width=width)

    def text(self, xy, s, size=20, fill=(255, 255, 255), bold=False, cn=False,
             anchor=None, mono=False):
        """支持多行(用 \\n 分隔); anchor 手动实现(PIL 7 原生不支持 anchor/textlength)"""
        f = font(size, bold, cn, mono)
        lines = str(s).split("\n")
        mk = (size, bold, cn, mono)
        m = _MC.get(mk)
        if m is None:
            m = f.getmetrics()
            _MC[mk] = m
        asc, desc = m
        lh = asc + desc
        x, y = xy
        if anchor:
            w = max([self.tw(ln, size, bold, cn, mono) for ln in lines] or [0])
            ax = anchor[0]
            ay = anchor[1] if len(anchor) > 1 else 'a'
            if ax == 'm':
                x -= w / 2.0
            elif ax == 'r':
                x -= w
            total = lh * len(lines)
            if ay == 'm':
                y -= total / 2.0
            elif ay == 's':
                y -= asc
            elif ay == 'b':
                y -= total
        for i, ln in enumerate(lines):
            self.d.text((x, y + i * lh), ln, font=f, fill=fill)

    def tw(self, s, size=20, bold=False, cn=False, mono=False):
        """文字宽度 (多行取最长一行; 兼容 PIL 7 的 textsize / PIL 8+ 的 textlength)

        ★ 加了缓存。上板 cProfile 显示 Font.getsize 一帧能被调 771 次、
          白花 30ms —— 因为 fbui.text() 带 anchor 时每条文字都要量一次宽度。
          同样的字串(按钮标签等)反复量，缓存掉最划算。
        """
        s = str(s)
        if "\n" in s:
            s = max(s.split("\n"), key=len)
        k = (s, size, bold, cn, mono)
        v = _TWC.get(k)
        if v is not None:
            return v
        f = font(size, bold, cn, mono)
        try:
            v = self.d.textlength(s, font=f)
        except AttributeError:
            v = self.d.textsize(s, font=f)[0]
        if len(_TWC) < 3000:
            _TWC[k] = v
        return v

    def line(self, xy, fill=(255, 255, 255), width=1):
        self.d.line(xy, fill=fill, width=width)

    def clear(self, c=(12, 16, 32)):
        self.d.rectangle([0, 0, self.w, self.h], fill=c)

    # ══════════════════════════════════════════════════════════════════
    #  ★★★ 贴图也要走色温补偿（2026-10-03）
    # ══════════════════════════════════════════════════════════════════
    # 踩坑：ColorDraw 只拦得到【ImageDraw 的绘图调用】。
    #   而壁纸、玻璃卡片底图、投影这些东西是用 img.paste() 贴上去的，
    #   根本不经过 ImageDraw ⇒ 它们的颜色【一点没被补偿】。
    #
    #   后果：桌面上最大的视觉面积就是壁纸，所以用户看到"没变"。
    #
    # 修法：加一个 Screen.paste()，先把要贴的图过一遍补偿再贴。
    #   ★ 补偿在【贴的那一刻】做一次，不是每帧做 ⇒ 依然零开销。
    #   ★ App 里把 scr.img.paste(...) 换成 scr.paste(...) 即可。
    # ══════════════════════════════════════════════════════════════════
    def _comp_image(self, im):
        """对一张 PIL 图像做色温补偿（返回新图；不需要补偿时原样返回）"""
        if getattr(self, "_ident", True):
            return im
        lut = ([self._rt[v] for v in range(256)]
               + [self._gt[v] for v in range(256)]
               + [self._bt[v] for v in range(256)])
        if im.mode == "RGBA":
            # ★ RGBA 不能直接 point（会把 alpha 也查表），拆开处理
            r, g, b, a = im.split()
            r = r.point(self._rt)
            g = g.point(self._gt)
            b = b.point(self._bt)
            return Image.merge("RGBA", (r, g, b, a))
        return im.point(lut)

    def paste(self, im, box=None, mask=None):
        """★ 带色温补偿的贴图（替代 scr.img.paste）

        用法和 PIL 的 Image.paste 一样：
            scr.paste(wall)                  # 左上角
            scr.paste(wall, (x, y))          # 指定位置
            scr.paste(im, (x, y), im)        # 带 mask

        ★ 注意：如果 im 是【已经补偿过的】东西（比如桌面缓存的 _bg），
          要用 scr.img.paste() 直接贴，不能再走这里 —— 否则双重补偿。
        """
        im2 = self._comp_image(im)
        if box is None:
            self.img.paste(im2)
        elif mask is None:
            self.img.paste(im2, box)
        else:
            self.img.paste(im2, box, mask)

    def reset_draw(self):
        """★ 重建绘图对象【并且重新包上 ColorDraw 代理】

        ★★★ 踩坑（很隐蔽）：
          desktop.py 里为了"换一张画布"写了一句
              scr.d = ImageDraw.Draw(scr.img)
          这句直接把 ColorDraw 代理【换成了原始 ImageDraw】，
          于是那之后画的所有东西都不再走色温补偿 ——
          表现为"有些界面补偿生效、有些没有"，很难查。

          统一改成调 scr.reset_draw()，就不会再漏。
        """
        self.d = ColorDraw(ImageDraw.Draw(self.img), self)

    def gradient_bg(self, top=(18, 26, 54), bottom=(8, 10, 22)):
        """竖直渐变背景"""
        for y in range(self.h):
            t = y / float(self.h)
            c = (int(top[0] + (bottom[0] - top[0]) * t),
                 int(top[1] + (bottom[1] - top[1]) * t),
                 int(top[2] + (bottom[2] - top[2]) * t))
            self.d.line([(0, y), (self.w, y)], fill=c)

# ---------------- 通用控件 ----------------
def hit(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


class ExitApp(BaseException):
    """「回桌面」异常 —— 由 Touch.poll() 在用户点了左上角返回区时抛出。

    ★ 为什么用 BaseException 而不是 Exception：
      应用里到处都有 `except Exception:` 兜底，如果继承 Exception 会被吃掉。
      继承 BaseException（和 KeyboardInterrupt 同级）就一定能穿出去。

    ★ 为什么要在 Touch 里做这件事（而不是每个应用各写一遍）：
      应用是跑在桌面进程里的（desktop.run_app 里 mod.run()），桌面主循环
      这时候是阻塞的，没法插手。但只要在**共用的 Touch 对象**上拦截，
      不管应用怎么写循环，点左上角都能立刻退出来 ——
      以后新加的应用也自动有这个能力，不会再出现"进得去出不来"。

    ★ 只在"应用自己不响应返回"时才触发（要点两次，见 _guard），
      所以不会抢掉小说/壁纸那种"返回时保存进度"的逻辑。
    """

def btn(scr, rect, label, fill=(56, 88, 148), tc=(255, 255, 255), size=22,
        cn=False, radius=10, bold=False, outline=None, mono=False):
    scr.rrect(list(rect), radius, fill=fill, outline=outline, width=2 if outline else 1)
    scr.text(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2), label, size, tc,
             cn=cn, anchor="mm", bold=bold, mono=mono)

# ★ 默认色改成暖色（原先观感）；原值 accent=(70,110,180) bg=(30,40,68)
def header(scr, title, accent=(180, 110, 70), bg=(68, 40, 30), cn=True):
    """顶部标题栏, 返回 [10,8,130,52]; 各应用自己判 hit"""
    scr.rect([0, 0, scr.w, 60], fill=bg)
    scr.rect([0, 58, scr.w, 62], fill=accent)
    btn(scr, [10, 8, 130, 52], "< 返回", fill=(100, 70, 60), size=22, cn=True)
    scr.text((150, 30), title, 26, (238, 244, 255), cn=cn, anchor="lm")

def back_hit(x, y):
    return hit([10, 8, 130, 52], x, y)

# ---------------- 屏上键盘 ----------------
class MiniKeyboard:
    ROWS = [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl."),
        list("zxcvbnm_-/"),
    ]
    def __init__(self, y0=372, key_w=88, key_h=48, gap=6, arrows=False):
        """arrows=True 时底部多一对左右方向键（移光标用）

        ★ 2026-10-03 加：用户要"闪烁的竖线可以调整输入位置"（参考 iPad）。
          光标左右移动需要方向键，所以给键盘补一对。
        ★ 默认 False —— 这个类被 4 个 App 共用
          （apps_agent / apps_browser / apps_term / apps_wifi），
          不传参数的地方布局【一个像素都不变】，不会把别的 App 搞乱。
        """
        self.y0, self.kw, self.kh, self.gap = y0, key_w, key_h, gap
        self.arrows = bool(arrows)
        self.keys = []
        for r, row in enumerate(self.ROWS):
            total = len(row) * key_w + (len(row) - 1) * gap
            x = (1024 - total) // 2
            y = y0 + r * (key_h + gap)
            for k in row:
                self.keys.append((k, [x, y, x + key_w, y + key_h]))
                x += key_w + gap
        # 底部功能键
        y = y0 + 4 * (key_h + gap)
        if self.arrows:
            self.sp = [80, y, 300, y + key_h]
            self.left = [308, y, 368, y + key_h]
            self.right = [376, y, 436, y + key_h]
            self.bs = [444, y, 664, y + key_h]
            self.ent = [672, y, 944, y + key_h]
        else:
            self.sp = [80, y, 384, y + key_h]
            self.left = None
            self.right = None
            self.bs = [392, y, 640, y + key_h]
            self.ent = [648, y, 944, y + key_h]
        self.shift = False
    def draw(self, scr):
        for k, r in self.keys:
            lbl = k.upper() if self.shift and k.isalpha() else k
            btn(scr, r, lbl, fill=(48, 60, 92), size=22, bold=True, radius=8)
        btn(scr, self.sp, "空格", fill=(48, 60, 92), size=20, cn=True, radius=8)
        if self.arrows:
            btn(scr, self.left, "\u25c0", fill=(56, 50, 74), size=20,
                bold=True, radius=8)
            btn(scr, self.right, "\u25b6", fill=(56, 50, 74), size=20,
                bold=True, radius=8)
        btn(scr, self.bs, "< 退格", fill=(120, 70, 60), size=20, cn=True, radius=8)
        btn(scr, self.ent, "回车", fill=(52, 120, 80), size=20, cn=True, radius=8)
    def press(self, x, y):
        for k, r in self.keys:
            if hit(r, x, y):
                return (k.upper() if self.shift and k.isalpha() else k)
        if hit(self.sp, x, y):
            return " "
        if self.arrows:
            if hit(self.left, x, y):
                return "<LEFT>"
            if hit(self.right, x, y):
                return "<RIGHT>"
        if hit(self.bs, x, y):
            return "<BS>"
        if hit(self.ent, x, y):
            return "<ENTER>"
        return None

# ---------------- 触摸 ----------------
def find_touch():
    name = ""
    for line in open("/proc/bus/input/devices"):
        line = line.strip()
        if line.startswith("N: Name="):
            name = line
        elif line.startswith("H: Handlers=") and name:
            if any(k in name for k in ("Goodix", "TouchScreen", "touch", "Touch")):
                for t in line.split():
                    if t.startswith("event"):
                        return "/dev/input/" + t
    return "/dev/input/event1"

EV = struct.calcsize("llHHi")

class Touch:
    def __init__(self):
        self.path = find_touch()
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        self.x = self.y = 0
        self.down = False
        self.sx = self.sy = 0
        self._inj = []          # 注入事件的待发队列(支持拖拽序列)
        self._pend = []         # 真实触摸解析出来的待发队列
        print("touch:", self.path)

    def _load_inject(self):
        """读取 /tmp/ui_tap, 支持三种格式:
             "x,y"                        —— 单次点击
             "drag:x1,y1;x2,y2;x3,y3"     —— 拖拽(产生 down/move.../up)
             "down:x,y" / "move:x,y" / "up:x,y"  —— 单独注入一个事件
                                                  (用来测试"长按", 因为长按需要真实时间间隔)
        """
        try:
            if not os.path.exists("/tmp/ui_tap"):
                return None
            txt = open("/tmp/ui_tap").read().strip()
            os.remove("/tmp/ui_tap")
            if not txt:
                return None
            if txt.startswith("drag:"):
                pts = []
                for seg in txt[5:].split(";"):
                    if "," in seg:
                        a, b = seg.split(",", 1)
                        pts.append((int(a), int(b)))
                if len(pts) >= 2:
                    evs = [("down", pts[0][0], pts[0][1])]
                    evs += [("move", p[0], p[1]) for p in pts[1:]]
                    evs.append(("up", pts[-1][0], pts[-1][1]))
                    self._inj = evs
                    return self._inj.pop(0)
            elif txt.startswith("down:") or txt.startswith("move:") or txt.startswith("up:"):
                kind, rest = txt.split(":", 1)
                pr = rest.split(",")
                x, y = int(pr[0]), int(pr[1])
                if kind == "down":
                    self.down = True
                    self.sx, self.sy = x, y
                elif kind == "up":
                    self.down = False
                self.x, self.y = x, y
                return (kind, x, y)
            else:
                pr = txt.split(",")
                return ("tap", int(pr[0]), int(pr[1]))
        except Exception:
            pass
        return None

    def poll(self, move=False):
        """返回事件:
             move=False:  ('tap',x,y) / None          —— 普通点击
             move=True :  ('down',x,y) ('move',x,y) ('up',x,y) / ('tap',x,y) / None
                          —— 连续绘制用; 必须处理 'up' 否则笔画会连起来
           远程注入: 向 /tmp/ui_tap 写 "x,y" 或 "drag:x1,y1;x2,y2;..." (调试用)

        ★ 重要: 一次 os.read 可能同时拿到 down/move/up 多个事件。
          必须把它们排队逐个返回, 不能只返回最后一个 ——
          否则 'down' 会被同批的 'up' 吃掉, 导致"点了没反应"(按钮失效)。

        ★ 左上角「返回区」: 桌面在跑应用时会把 self.exit_zone 设上，
          点到这里就抛 ExitApp，任何应用都能立刻退回桌面。
        """
        # ---- 先发队列里剩下的 ----
        if self._inj:
            return self._guard(self._inj.pop(0))
        if self._pend:
            return self._guard(self._pend.pop(0))
        # ---- 远程注入 ----
        r = self._load_inject()
        if r is not None:
            if r[0] in ("down", "move", "up") and not move:
                return None          # 拖拽事件只给 move=True 的应用
            return self._guard(r)
        # ---- 真实触摸: 解析整批 -> 排队 ----
        try:
            data = os.read(self.fd, EV * 256)
        except OSError:
            return None
        if not data:
            return None
        evs = []
        # ★ 触摸屏的 X / Y 是分两个事件送来的。必须等两个都更新过才发一个 move,
        #   否则会发出"半新半旧"的坐标, 画线时来回跳 -> 看起来是折线。
        gotx = goty = False
        for i in range(0, len(data) - EV + 1, EV):
            _, _, et, code, val = struct.unpack("llHHi", data[i:i + EV])
            if et == 3:
                if code in (0x35, 0):
                    self.x = val
                    gotx = True
                elif code in (0x36, 1):
                    self.y = val
                    goty = True
                if move and self.down and gotx and goty:
                    evs.append(("move", self.x, self.y))
                    gotx = goty = False
            elif et == 1 and code == 0x14A:
                if val == 1 and not self.down:
                    self.down = True
                    self.sx, self.sy = self.x, self.y
                    if move:
                        evs.append(("down", self.x, self.y))    # 落笔
                elif val == 0 and self.down:
                    self.down = False
                    if move:
                        evs.append(("up", self.x, self.y))      # ★ 抬笔
                    elif abs(self.x - self.sx) < 60 and abs(self.y - self.sy) < 60:
                        evs.append(("tap", self.x, self.y))
        # 丢掉连续重复的点 (手指没动的采样), 减少无谓重绘
        if len(evs) > 2:
            out = [evs[0]]
            for e in evs[1:]:
                p = out[-1]
                if e[0] == "move" and p[0] == "move" and e[1] == p[1] and e[2] == p[2]:
                    continue                      # 和上一个点完全相同 -> 丢
                out.append(e)
            evs = out
        if evs:
            self._pend = evs
            return self._guard(self._pend.pop(0))
        return None

    # ---- 左上角「返回区」拦截（桌面跑应用时用）----
    exit_zone = None          # 例: (0, 0, 132, 58)；None = 不拦截
    _ez_t = 0.0               # 上一次点返回区的时间
    EZ_ARM = 3.0              # 第一次点只"上膛"，3 秒内再点一次才强制退出

    def _guard(self, ev):
        """点了返回区的第二次 -> 抛 ExitApp 强退。

        ★ 为什么要点两次：
          小说阅读器 / 壁纸 / 文件 这些应用**在返回时才会存进度/设置**。
          如果第一次点就被我们抢走抛异常，它们的保存逻辑永远跑不到。
          所以：
            * 应用自己处理返回的（绝大多数）—— 第一次点就正常退出，
              根本轮不到这里；
            * 真正卡住出不来的应用 —— 再点一次（3 秒内）就强制退出去。
        """
        z = self.exit_zone
        if z and ev and ev[0] in ("tap", "up"):
            x, y = ev[1], ev[2]
            if z[0] <= x <= z[2] and z[1] <= y <= z[3]:
                now = time.time()
                if now - self._ez_t <= self.EZ_ARM:
                    self._ez_t = 0.0
                    raise ExitApp()
                self._ez_t = now
        return ev


# =====================================================================
#  卡片 / 玻璃材质 —— 首页卡片化改版新增 (纯追加, 不影响上面任何旧代码)
#
#  为什么要做缓存:
#    这个屏是【软件渲染】, 每帧重画 1024x600 的圆角+渐变+阴影非常贵。
#    卡片底图在一次渲染里是不变的 -> 生成一次存成 PIL 图像, 之后只 paste。
#  为什么要 2 倍超采样:
#    PIL 画圆角是"直线+扇形"拼的, 圆角边缘有锯齿。放到 2 倍再 LANCZOS
#    缩回来, 边缘就平滑了 —— 这是整个观感提升最大的一步。
# =====================================================================

# =====================================================================
#  ★★★ 模块级的圆角矩形（2026-10-03）
# =====================================================================
#  为什么要抽出来：
#    · PIL 7.0【没有】ImageDraw.rounded_rectangle（板子上就报
#      AttributeError: 'ImageDraw' object has no attribute
#      'rounded_rectangle'），所以一直是自己拼的。
#    · 原来这段逻辑写在 Screen.rrect 里，只能画在 self.d 上。
#      但 home.build_static() 是在【一张离屏图】上用局部变量 d
#      (ImageDraw.Draw(im)) 画静态层的 —— 那里想画圆角矩形就没办法。
#    · 结果就是"全部应用"按钮在卡片首页漏画（见 home.build_static）。
#  ⇒ 抽成模块级函数，Screen 和离屏静态层都能用。
# =====================================================================
def rrect_draw(d, xy, r, fill=None, outline=None, width=1):
    """在任意 ImageDraw 上画圆角矩形（PIL 7.0 兼容）

    d       : PIL.ImageDraw.Draw 出来的对象
    xy      : (x0, y0, x1, y1)
    r       : 圆角半径（会自动夹到不超过短边一半）
    """
    x0, y0, x1, y1 = xy
    r = int(max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2)))
    if fill:
        d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for (cx, cy) in ((x0, y0), (x1 - 2 * r, y0),
                         (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
            d.ellipse([cx, cy, cx + 2 * r, cy + 2 * r], fill=fill)
    if outline and width > 0:
        for k in range(width):
            d.arc([x0 + k, y0 + k, x0 + 2 * r - k, y0 + 2 * r - k],
                  180, 270, fill=outline)
            d.arc([x1 - 2 * r + k, y0 + k, x1 - k, y0 + 2 * r - k],
                  270, 360, fill=outline)
            d.arc([x0 + k, y1 - 2 * r + k, x0 + 2 * r - k, y1 - k],
                  90, 180, fill=outline)
            d.arc([x1 - 2 * r + k, y1 - 2 * r + k, x1 - k, y1 - k],
                  0, 90, fill=outline)
        d.line([x0 + r, y0, x1 - r, y0], fill=outline, width=width)
        d.line([x0 + r, y1, x1 - r, y1], fill=outline, width=width)
        d.line([x0, y0 + r, x0, y1 - r], fill=outline, width=width)
        d.line([x1, y0 + r, x1, y1 - r], fill=outline, width=width)


def _rr_mask(size, radius, ss=2):
    """生成圆角矩形的抗锯齿遮罩 (L 模式)。ss = 超采样倍数。"""
    from PIL import ImageChops  # noqa: F401
    w, h = int(size[0]), int(size[1])
    radius = max(0, min(int(radius), w // 2, h // 2))
    if radius <= 0:
        return Image.new("L", (w, h), 255)
    W, H, R = w * ss, h * ss, radius * ss
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rectangle([R, 0, W - 1 - R, H - 1], fill=255)
    d.rectangle([0, R, W - 1, H - 1 - R], fill=255)
    for cx, cy in ((0, 0), (W - 2 * R, 0), (0, H - 2 * R), (W - 2 * R, H - 2 * R)):
        d.ellipse([cx, cy, cx + 2 * R - 1, cy + 2 * R - 1], fill=255)
    return m.resize((w, h), _RESAMPLE)


# 老版本 Pillow 没有 Image.LANCZOS（或者是 Resampling 枚举），取一个安全的
_RESAMPLE = getattr(Image, "LANCZOS", None)
if _RESAMPLE is None:
    _RESAMPLE = getattr(Image, "BICUBIC", 3)


def vgrad(size, top, bottom, alpha=255):
    """竖直渐变图 (RGBA)"""
    w, h = int(size[0]), int(size[1])
    im = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(im)
    hh = max(1, h - 1)
    for y in range(h):
        t = y / float(hh)
        c = (int(top[0] + (bottom[0] - top[0]) * t),
             int(top[1] + (bottom[1] - top[1]) * t),
             int(top[2] + (bottom[2] - top[2]) * t), alpha)
        d.line([(0, y), (w, y)], fill=c)
    return im


def shadow(size, radius, spread=10, alpha=90, offset=(0, 4)):
    """卡片投影 (RGBA, 比卡片本体大 spread 一圈)"""
    w, h = int(size[0]), int(size[1])
    canvas = (w + spread * 2, h + spread * 2)
    m = _rr_mask((w, h), radius)
    im = Image.new("RGBA", canvas, (0, 0, 0, 0))
    blk = Image.new("RGBA", (w, h), (0, 0, 0, alpha))
    im.paste(blk, (spread + offset[0], spread + offset[1]), m)
    return im.filter(ImageFilter.GaussianBlur(spread * 0.55))


def glass(size, radius=18, top=(30, 38, 60), bot=(14, 19, 32), alpha=0.78,
          border=(255, 255, 255), border_a=30, gloss=16):
    """深色玻璃卡片底图 (RGBA)。

    top/bot  : 竖向渐变的上下颜色
    alpha    : 整体不透明度 0~1
    border   : 描边颜色; border_a = 描边不透明度(0~255)
    gloss    : 顶部柔光强度(0 关闭) —— 玻璃感的主要来源
    """
    from PIL import ImageChops
    w, h = int(size[0]), int(size[1])
    mask = _rr_mask((w, h), radius)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(vgrad((w, h), top, bot, int(255 * alpha)), (0, 0), mask)

    # 顶部柔光: 上亮下透, 模拟玻璃受光
    if gloss > 0:
        gh = max(8, int(h * 0.42))
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for y in range(gh):
            a = int(gloss * (1.0 - y / float(gh)) ** 1.6)
            if a > 0:
                gd.line([(0, y), (w, y)], fill=(255, 255, 255, a))
        cut = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cut.paste(g, (0, 0), mask)
        out = Image.alpha_composite(out, cut)

    # 1px 描边 (用"外遮罩 - 内遮罩"得到环)
    if border_a > 0 and w > 3 and h > 3:
        inner = Image.new("L", (w, h), 0)
        inner.paste(_rr_mask((w - 2, h - 2), max(0, radius - 1)), (1, 1))
        ring = ImageChops.subtract(mask, inner)
        out.paste(Image.new("RGBA", (w, h), tuple(border) + (border_a,)), (0, 0), ring)
    return out


def blank(size, radius=18):
    """透明占位 (给没有内容的格子用)"""
    return Image.new("RGBA", (int(size[0]), int(size[1])), (0, 0, 0, 0))

