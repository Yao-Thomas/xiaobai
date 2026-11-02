#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_gpu.py —— FPGA 2D 加速器 【测试台】

这是整个系统里【唯一】会去碰自研 GPU 的地方 —— 桌面默认不使用 GPU
(见 desktop.py 的 try_gpu 注释: PL 的 AXI 口只有 100 MHz,
 800 MB/s 的天花板打不过 A9 核的 1853 MB/s, 桌面上全是小矩形更吃亏)。

这个应用做四件事:
  1. 填充测试 + 【逐字节回读校验】  —— 证明硬件真的写对了
  2. 画线测试 (Bresenham) + 校验
  3. GPU vs CPU 公平对比            —— 同一份矩形表, 区别只在出口
  4. 寄存器快照                     —— 证明 IP 真的在线

★ 安全: 只有在 /home/zynq/.gpu_addr 存在时才去碰 /dev/mem。
  访问未解码的地址会触发 SIGBUS, Python 抓不住, 进程会直接被打死。
"""
import time

from fbui import header, back_hit, btn, hit

MARKER = "/home/zynq/.gpu_addr"
GPU_BASE = 0x43CB0000

# 演示区: GPU 往这块直接画, 校验也从这块读回来
DEMO = [56, 258, 968, 420]
LOG_Y0 = 436
LOG_N = 6


# ---------------------------------------------------------------- 探测
def find(scr):
    """返回 (GpuFill, 说明) ; 拿不到就 (None, 原因)"""
    try:
        addr = int(open(MARKER).read().strip(), 0)
    except Exception:
        return None, "缺 %s (bitstream 里没集成 GPU?)" % MARKER
    if not getattr(scr, "phys", 0):
        return None, "拿不到显存物理地址"
    try:
        from gpufill import GpuFill
        gf = GpuFill(scr, base=addr, verbose=False)
        if not gf.hw:
            return None, gf.why
        return gf, "0x%08X" % addr
    except Exception as ex:
        return None, "加载驱动失败: %s" % ex


def regs(addr):
    """读一遍寄存器, 返回字符串列表"""
    out = []
    try:
        from gpu import GPU
        g = GPU(addr, verbose=False)
        names = [(0x00, "CTRL"), (0x04, "OP"), (0x08, "BASE"), (0x0C, "STRIDE"),
                 (0x10, "XY0"), (0x14, "XY1"), (0x18, "COLOR"),
                 (0x1C, "PIXCNT"), (0x20, "STATUS")]
        for off, nm in names:
            out.append("+0x%02X %-7s = 0x%08X" % (off, nm, g.rd(off) & 0xFFFFFFFF))
        g.close()
    except Exception as ex:
        out.append("读寄存器失败: %s" % ex)
    return out


# ---------------------------------------------------------------- 校验
def verify(scr, x0, y0, x1, y1, color):
    """从 mmap 逐字节回读, 和期望的 BGR 流比对。返回 (坏行数, 总行数, 首个错误)"""
    if scr.yoff != 0:
        return -1, 0, "当前显示的不是 page 0 (pan=%d), 校验无意义" % scr.yoff
    b = color & 0xFF
    g = (color >> 8) & 0xFF
    r = (color >> 16) & 0xFF
    exp = bytes((b, g, r)) * (x1 - x0 + 1)
    bad = 0
    first = ""
    for y in range(y0, y1 + 1):
        o = y * scr.stride + x0 * 3
        got = scr.mm[o:o + len(exp)]
        if got != exp:
            bad += 1
            if not first:
                for k in range(len(exp)):
                    if got[k] != exp[k]:
                        first = "y=%d 第%d字节 got=%02X 应为%02X" % (
                            y, k, got[k], exp[k])
                        break
    return bad, (y1 - y0 + 1), first


# ---------------------------------------------------------------- 绘制
def draw(scr, st):
    scr.clear((17, 17, 17))
    header(scr, "FPGA 2D 加速器 测试台")

    y = 66
    if st["gf"]:
        scr.rrect([52, y, scr.w - 52, y + 74], 10,
                  fill=(20, 52, 38), outline=(70, 200, 130), width=2)
        scr.text((74, y + 20), "GPU 在线 %s" % st["addr"], 22, (130, 245, 180),
                 cn=True, bold=True, anchor="lm")
        scr.text((74, y + 50),
                 "显存 0x%08X   stride %d   24bpp packed BGR   8 字节/拍 @100MHz"
                 % (st["phys"], st["stride"]),
                 15, (165, 215, 195), cn=True, anchor="lm")
    else:
        scr.rrect([52, y, scr.w - 52, y + 74], 10,
                  fill=(56, 34, 24), outline=(200, 140, 70), width=2)
        scr.text((74, y + 20), "GPU 不可用", 22, (255, 195, 115),
                 cn=True, bold=True, anchor="lm")
        scr.text((74, y + 50), str(st["why"])[:80], 15, (218, 188, 150),
                 cn=True, anchor="lm")

    y += 90
    bw = (scr.w - 104 - 3 * 10) // 4
    labels = [("填充+校验", (44, 104, 172)),
              ("画线+校验", (40, 132, 104)),
              ("GPU vs CPU", (146, 88, 40)),
              ("寄存器", (104, 60, 140))]
    st["btns"] = []
    for i, (lbl, col) in enumerate(labels):
        r = [52 + i * (bw + 10), y, 52 + i * (bw + 10) + bw, y + 54]
        btn(scr, r, lbl, fill=col, size=19, cn=True)
        st["btns"].append(r)

    # 演示区: 只画边框, 里面留给 GPU
    scr.rrect([DEMO[0] - 2, DEMO[1] - 2, DEMO[2] + 2, DEMO[3] + 2], 8,
              fill=None, outline=(58, 82, 124), width=2)
    scr.text((DEMO[0], DEMO[1] - 20),
             "演示区 (GPU 直接写显存, 校验就从这里逐字节读回来)",
             15, (120, 152, 200), cn=True)

    # 日志区
    scr.rrect([52, LOG_Y0 - 8, scr.w - 52, scr.h - 16], 8,
              fill=(10, 10, 10), outline=(46, 64, 100))
    yy = LOG_Y0 + 4
    for line, col in st["log"][-LOG_N:]:
        scr.text((70, yy), line[:86], 17, col, cn=True)
        yy += 25


def push(st, line, col=(168, 226, 188)):
    st["log"].append((line, col))


def flush_log(scr, st):
    """只重画日志区 —— 演示区的 GPU 像素要留着"""
    scr.rrect([52, LOG_Y0 - 8, scr.w - 52, scr.h - 16], 8,
              fill=(10, 10, 10), outline=(46, 64, 100))
    yy = LOG_Y0 + 4
    for line, col in st["log"][-LOG_N:]:
        scr.text((70, yy), line[:86], 17, col, cn=True)
        yy += 25
    scr.flush(box=(50, LOG_Y0 - 10, scr.w - 50, scr.h - 14))


# ---------------------------------------------------------------- 功能
def test_fill(scr, st):
    gf = st["gf"]
    if not gf:
        push(st, "没有 GPU, 跳过", (240, 180, 120))
        return
    push(st, "-- 填充 + 逐字节校验 --", (200, 220, 255))
    cols = [0xE03038, 0x30C060, 0x3070E0, 0xE0C030]
    w = (DEMO[2] - DEMO[0] - 5 * 16) // 4
    tot_bad = 0
    for i, c in enumerate(cols):
        x0 = DEMO[0] + 16 + i * (w + 16)
        x1 = x0 + w - 1
        t0 = time.time()
        gf.begin()
        gf.rect(x0, DEMO[1] + 16, x1, DEMO[3] - 16, c)
        gf.commit()
        ms = gf.ms
        bad, nrow, first = verify(scr, x0, DEMO[1] + 16, x1, DEMO[3] - 16, c)
        tot_bad += max(0, bad)
        push(st, "  块%d #%06X  %6.2f ms  %4d 行  %s"
             % (i + 1, c, ms, nrow,
                "校验 OK" if bad == 0 else "校验错 %d 行 %s" % (bad, first)),
             (150, 230, 170) if bad == 0 else (255, 140, 140))
    push(st, "  合计: 错 %d 行" % tot_bad,
         (150, 230, 170) if tot_bad == 0 else (255, 140, 140))
    if st["yoff_note"]:
        push(st, st["yoff_note"], (240, 190, 120))


def test_line(scr, st):
    gf = st["gf"]
    if not gf:
        push(st, "没有 GPU, 跳过", (240, 180, 120))
        return
    push(st, "-- 画线 (Bresenham) --", (200, 220, 255))
    t0 = time.time()
    gf.begin()
    for i in range(6):
        yy = DEMO[1] + 20 + i * 24
        gf.line(DEMO[0] + 12, yy, DEMO[2] - 12, yy + (12 if i % 2 else -12),
                0x00FFAA)
    gf.commit()
    push(st, "  6 条斜线  %.2f ms" % gf.ms)
    push(st, "  采样校验:", (200, 220, 255))
    if scr.yoff != 0:
        push(st, "  " + st["yoff_note"], (240, 190, 120))
        return
    okc = 0
    for i in range(6):
        yy = DEMO[1] + 20 + i * 24
        o = yy * scr.stride + (DEMO[0] + 12) * 3
        if bytes(scr.mm[o:o + 3]) == bytes((0xAA, 0xFF, 0x00)):
            okc += 1
    push(st, "  6 个起点像素对上了 %d 个" % okc,
         (150, 230, 170) if okc == 6 else (255, 180, 120))


def test_vs_cpu(scr, st):
    gf = st["gf"]
    if not gf:
        push(st, "没有 GPU, 跳过", (240, 180, 120))
        return
    push(st, "-- GPU vs CPU (同一份矩形表) --", (200, 220, 255))
    # 在演示区铺一张 24 个小矩形的网格
    rects = []
    for gy in range(3):
        for gx in range(8):
            x0 = DEMO[0] + 14 + gx * ((DEMO[2] - DEMO[0] - 20) // 8)
            y0 = DEMO[1] + 14 + gy * ((DEMO[3] - DEMO[1] - 20) // 3)
            rects.append((x0, y0, x0 + 88, y0 + 40,
                          0x204080 + (gx + gy * 8) * 0x000A08))
    npx = sum((c - a + 1) * (d - b + 1) for (a, b, c, d, _) in rects)

    # GPU
    t0 = time.time()
    gf.begin()
    for (a, b, c, d, col) in rects:
        gf.rect(a, b, c, d, col)
    gf.commit()
    ms_gpu = gf.ms
    if scr.yoff == 0:
        bad, nrow, _ = verify(scr, rects[0][0], rects[0][1],
                              rects[0][2], rects[0][3], rects[0][4])
    else:
        bad = 0
    # CPU: 完全一样的矩形表, 只是出口换成 C 填充器
    gf.lib.cb_stats_reset()
    for _ in range(5):
        gf.begin()
        for (a, b, c, d, col) in rects:
            gf.rect(a, b, c, d, col)
        gf.commit_cpu()
    ms_cpu, _p = gf.cpu_stats()
    ms_cpu /= 5.0

    push(st, "  矩形 %d 个 / %d 像素" % (len(rects), npx))
    push(st, "  FPGA GPU  %6.2f ms   (%.0f MB/s)"
         % (ms_gpu, npx * 3 / ms_gpu / 1000.0), (170, 220, 255))
    push(st, "  CPU C填充 %6.2f ms   (%.0f MB/s)"
         % (ms_cpu, npx * 3 / ms_cpu / 1000.0), (255, 214, 170))
    if ms_gpu < ms_cpu:
        push(st, "  -> GPU 快 %.2f 倍" % (ms_cpu / ms_gpu), (150, 240, 170))
    else:
        push(st, "  -> GPU 慢 %.2f 倍 (100MHz PL 的 800MB/s 天花板)"
             % (ms_gpu / ms_cpu), (255, 170, 170))
    push(st, "  第一个方块校验: %s"
         % ("OK" if bad == 0 else "错 %d 行" % bad),
         (150, 230, 170) if bad == 0 else (255, 140, 140))


def test_regs(st):
    push(st, "-- 寄存器快照 --", (200, 220, 255))
    for line in regs(GPU_BASE):
        push(st, "  " + line, (170, 214, 240))


# ---------------------------------------------------------------- 主循环
def run(scr, touch):
    st = {"gf": None, "why": "", "log": [], "btns": [],
          "addr": "", "phys": getattr(scr, "phys", 0),
          "stride": getattr(scr, "stride", 0), "yoff_note": ""}

    # 自研 GPU 只写物理基址开始的 page 0, 显示也得在 page 0 校验才有意义
    if getattr(scr, "yoff", 0) != 0:
        try:
            scr.pan(0)
        except Exception:
            st["yoff_note"] = "注意: 当前 pan 页 != 0, 校验已跳过"
    if getattr(scr, "yoff", 0) != 0:
        st["yoff_note"] = "注意: pan=%d (不是 page 0), 校验已跳过" % scr.yoff

    push(st, "正在探测 FPGA GPU ...")
    gf, why = find(scr)
    st["gf"] = gf
    st["why"] = why
    if gf:
        st["addr"] = why
        push(st, "找到 GPU @%s" % why, (160, 240, 180))
        push(st, "驱动: gpubatch (C 批量), 8 字节/拍")
    else:
        st["addr"] = ""
        push(st, "没找到 GPU: %s" % why, (250, 180, 120))
        push(st, "下面的按钮会提示跳过", (200, 170, 130))

    draw(scr, st)
    scr.flush()

    while True:
        ev = touch.poll()
        if ev:
            _, x, y = ev
            if back_hit(x, y):
                return
            b = st["btns"]
            try:
                if hit(b[0], x, y):
                    test_fill(scr, st)
                elif hit(b[1], x, y):
                    test_line(scr, st)
                elif hit(b[2], x, y):
                    test_vs_cpu(scr, st)
                elif hit(b[3], x, y):
                    test_regs(st)
                else:
                    continue
                flush_log(scr, st)
            except Exception as ex:
                push(st, "出错: %s" % ex, (255, 150, 150))
                flush_log(scr, st)
        time.sleep(0.03)
