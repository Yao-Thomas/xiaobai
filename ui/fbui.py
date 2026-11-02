#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fbui.py —— Zynq 板载 7 寸屏(1024x600 24bpp) 图形库
  用 PIL 画图 -> 转 BGR;24 -> 直接写 /dev/fb0
  触摸用 evdev 读 GT911
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

# ---------------- 屏幕 ----------------
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
        self.d = ImageDraw.Draw(self.img)
        self.mode = {24: "BGR;24", 32: "BGRA"}.get(self.bpp, "BGR;24")
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
        """把 PIL 图像推到屏幕; box=(x0,y0,x1,y1) 只推局部"""
        if box is None or not self._fast:
            if box is None:
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
    #   flush() 每次都要 crop + convert("BGR;24") + tobytes(), 在板子上
    #   1024x96 的区域光转换就 4.6ms。对【每帧都不变】的 UI (信息栏背景、
    #   按钮) 完全没必要重复转换 —— 转一次存下来, 之后只做内存写。
    def to_raw(self, im):
        """把 PIL 图像预转成和显存一致的原始字节 (BGR;24), 供 blit_raw 用"""
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
        x0, y0, x1, y1 = xy
        r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
        if fill:
            self.d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
            self.d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
            for (cx, cy) in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
                self.d.ellipse([cx, cy, cx + 2 * r, cy + 2 * r], fill=fill)
        if outline and width > 0:
            for k in range(width):
                self.d.arc([x0 + k, y0 + k, x0 + 2 * r - k, y0 + 2 * r - k], 180, 270, fill=outline)
                self.d.arc([x1 - 2 * r + k, y0 + k, x1 - k, y0 + 2 * r - k], 270, 360, fill=outline)
                self.d.arc([x0 + k, y1 - 2 * r + k, x0 + 2 * r - k, y1 - k], 90, 180, fill=outline)
                self.d.arc([x1 - 2 * r + k, y1 - 2 * r + k, x1 - k, y1 - k], 0, 90, fill=outline)
            self.d.line([x0 + r, y0, x1 - r, y0], fill=outline, width=width)
            self.d.line([x0 + r, y1, x1 - r, y1], fill=outline, width=width)
            self.d.line([x0, y0 + r, x0, y1 - r], fill=outline, width=width)
            self.d.line([x1, y0 + r, x1, y1 - r], fill=outline, width=width)

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

def header(scr, title, accent=(70, 110, 180), bg=(30, 40, 68), cn=True):
    """顶部标题栏, 返回 [10,8,130,52]; 各应用自己判 hit"""
    scr.rect([0, 0, scr.w, 60], fill=bg)
    scr.rect([0, 58, scr.w, 62], fill=accent)
    btn(scr, [10, 8, 130, 52], "< 返回", fill=(60, 70, 100), size=22, cn=True)
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
    def __init__(self, y0=372, key_w=88, key_h=48, gap=6):
        self.y0, self.kw, self.kh, self.gap = y0, key_w, key_h, gap
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
        self.sp = [80, y, 384, y + key_h]
        self.bs = [392, y, 640, y + key_h]
        self.ent = [648, y, 944, y + key_h]
        self.shift = False
    def draw(self, scr):
        for k, r in self.keys:
            lbl = k.upper() if self.shift and k.isalpha() else k
            btn(scr, r, lbl, fill=(48, 60, 92), size=22, bold=True, radius=8)
        btn(scr, self.sp, "空格", fill=(48, 60, 92), size=20, cn=True, radius=8)
        btn(scr, self.bs, "< 退格", fill=(120, 70, 60), size=20, cn=True, radius=8)
        btn(scr, self.ent, "回车", fill=(52, 120, 80), size=20, cn=True, radius=8)
    def press(self, x, y):
        for k, r in self.keys:
            if hit(r, x, y):
                return (k.upper() if self.shift and k.isalpha() else k)
        if hit(self.sp, x, y):
            return " "
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

