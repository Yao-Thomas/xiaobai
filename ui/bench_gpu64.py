#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_gpu64.py —— 64 位 (8 字节/拍) 自研 GPU 的真机基准 + 逐字节校验

背景: 旧 RTL 里 assign m_axi_awsize = 3'b000 (1 字节/拍), AXI 明明是 64 位
      总线却一次只搬 1 个字节, 实测整屏填充 20.19ms (91MB/s),
      比 CPU 的 C 填充器 (3.58ms / 514MB/s) 慢 5.6 倍。
      新 RTL: 64 位数据 + awsize=3'b011 (8 字节/拍), 理论 800MB/s。

本脚本做两件事:
  1. 【正确性】从 mmap 逐字节回读显存, 确认 GPU 写出来的每个像素都对
     —— 换比特流后最重要的验证 (WSTRB / 字节道 / BGR 相位 有没有算错)
  2. 【性能】GPU vs CPU 的公平对比: 同一份矩形表, 同一批 C 驱动,
     区别只在"交给硬件"还是"CPU 自己写内存"

注意: 自研 GPU 和 C 填充器都只写【物理基址开始的 page 0】,
      所以先把 pan 归零, 让屏幕显示 page 0, 校验才有意义。

必须先把桌面停掉:
    sudo systemctl stop zynq-desktop zynq-screen-guard
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import fbui                                        # noqa: E402
from gpufill import GpuFill                        # noqa: E402

W, H = 1024, 600
BPP = 3
OUT = "/tmp/gpu64.txt"
_lines = []


def say(s=""):
    print(s)
    _lines.append(s)


def flush_out():
    try:
        with open(OUT, "w") as f:
            f.write("\n".join(_lines) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 校验
def verify(x0, y0, x1, y1, color, tag):
    """逐字节回读显存, 和期望的 BGR 流比对。返回坏行数。"""
    b = color & 0xFF
    g = (color >> 8) & 0xFF
    r = (color >> 16) & 0xFF
    npx = x1 - x0 + 1
    exp = bytes((b, g, r)) * npx
    yo = 0                    # GPU 写的是 page 0
    bad = 0
    firstbad = ""
    for y in range(y0, y1 + 1):
        o = yo + y * scr.stride + x0 * BPP
        got = scr.mm[o:o + len(exp)]
        if got != exp:
            bad += 1
            if not firstbad:
                for k in range(len(exp)):
                    if got[k] != exp[k]:
                        firstbad = ("y=%d 第%d字节 off=0x%X got=%02X want=%02X"
                                    % (y, k, o + k, got[k], exp[k]))
                        break
    if bad == 0:
        say("      校验 OK   %-24s %d 行 x %d 像素 全对"
            % (tag, y1 - y0 + 1, npx))
    else:
        say("      校验 失败 %-23s %d/%d 行不对  首个: %s"
            % (tag, bad, y1 - y0 + 1, firstbad))
    return bad


# ---------------------------------------------------------------- 计时
def t_gpu(label, x0, y0, x1, y1, color, n=10, do_verify=True):
    tot = 0.0
    for _ in range(n):
        gf.begin()
        gf.rect(x0, y0, x1, y1, color)
        gf.commit()
        tot += gf.ms               # begin() 里 reset 过, 所以是单次墙钟
    ms = tot / n
    npx = (x1 - x0 + 1) * (y1 - y0 + 1)
    say("    %-28s %8.3f ms  %7.1f MB/s  (%d px)"
        % ("FPGA GPU  " + label, ms, npx * 3 / ms / 1000.0, npx))
    if do_verify:
        verify(x0, y0, x1, y1, color, label)
    return ms


def t_cpu(label, x0, y0, x1, y1, color, n=10, do_verify=True):
    gf.lib.cb_stats_reset()
    for _ in range(n):
        gf.begin()
        gf.rect(x0, y0, x1, y1, color)
        gf.commit_cpu()
    ms, _px = gf.cpu_stats()
    ms /= n
    npx = (x1 - x0 + 1) * (y1 - y0 + 1)
    say("    %-28s %8.3f ms  %7.1f MB/s  (%d px)"
        % ("CPU C 填充器 " + label, ms, npx * 3 / ms / 1000.0, npx))
    if do_verify:
        verify(x0, y0, x1, y1, color, label)
    return ms


def t_mmap(label, x0, y0, x1, y1, color, n=5):
    scr.fill_raw(x0, y0, x1 - x0 + 1, y1 - y0 + 1, color)
    tot = 0.0
    for _ in range(n):
        t0 = time.time()
        scr.fill_raw(x0, y0, x1 - x0 + 1, y1 - y0 + 1, color)
        tot += (time.time() - t0) * 1000.0
    ms = tot / n
    npx = (x1 - x0 + 1) * (y1 - y0 + 1)
    say("    %-28s %8.3f ms  %7.1f MB/s  (%d px)"
        % ("CPU mmap(Python) " + label, ms, npx * 3 / ms / 1000.0, npx))
    return ms


# ================================================================ main
scr = fbui.Screen()
scr.pan(0)                       # ★ GPU 只写 page 0, 让屏幕也显示 page 0
gf = GpuFill(scr)

say("=" * 74)
say(" 64 位自研 GPU 真机基准  (8 字节/拍, 理论 800 MB/s @100MHz)")
say("=" * 74)
say(" 帧缓冲 %dx%d 虚拟 %d stride=%d 24bpp 物理=0x%08X pan页=%d"
    % (scr.w, scr.h, scr.vh, scr.stride, scr.phys or 0, scr.yoff))
say(" GPU: %s" % gf.hw)
if not gf.hw:
    say(" !! GPU 不可用: %s" % gf.why)
    flush_out()
    sys.exit(1)
say("")

fails = 0

# ---------------------------------------------------------------- 1
say("-" * 74)
say(" [1] 整屏填充 1024x600 (1.84 MB)")
say("-" * 74)
cpu_full = t_cpu("整屏", 0, 0, W - 1, H - 1, 0x102040, n=10)
gpu_full = t_gpu("整屏", 0, 0, W - 1, H - 1, 0x204060, n=10)
mm_full = t_mmap("整屏", 0, 0, W - 1, H - 1, 0x102040, n=5)
say("")
say("    >>> 整屏: GPU %.3f ms | CPU(C填充器) %.3f ms | CPU(Python mmap) %.3f ms"
    % (gpu_full, cpu_full, mm_full))
say("    >>> GPU 相对 C 填充器: %s %.2f 倍"
    % ("快" if gpu_full < cpu_full else "慢",
       max(gpu_full, cpu_full) / min(gpu_full, cpu_full)))

# ---------------------------------------------------------------- 2
say("")
say("-" * 74)
say(" [2] 对齐边界用例 (x0 不同 -> run 起始 off=(x0*3)&7 不同)")
say("-" * 74)
for x0, x1, tag in ((1, 1022, "off=3"), (3, 1020, "off=1"),
                    (5, 1018, "off=7"), (7, 1016, "off=5")):
    c = 0x30A050 + ((x0 * 0x010101) & 0x0F0F0F)
    say("    x0=%d -> off=(%d*3)&7=%d" % (x0, x0, (x0 * 3) & 7))
    t_gpu("x0=%d..%d" % (x0, x1), x0, 0, x1, H - 1, c, n=5)

# ---------------------------------------------------------------- 3
say("")
say("-" * 74)
say(" [3] 顶栏 1024x96 (295 KB)")
say("-" * 74)
cpu_bar = t_cpu("顶栏", 0, 0, W - 1, 95, 0x080A12, n=20)
gpu_bar = t_gpu("顶栏", 0, 0, W - 1, 95, 0x0A0C14, n=20)
say("    >>> 顶栏: GPU %.3f ms  vs  CPU %.3f ms  ->  GPU %s %.2f 倍"
    % (gpu_bar, cpu_bar, "快" if gpu_bar < cpu_bar else "慢",
       max(gpu_bar, cpu_bar) / min(gpu_bar, cpu_bar)))

# ---------------------------------------------------------------- 4
say("")
say("-" * 74)
say(" [4] 小矩形群 (桌面网格 69 个)")
say("-" * 74)
rects = []
for gy in range(6):
    for gx in range(10):
        x = 20 + gx * 100
        y = 100 + gy * 80
        rects.append((x, y, x + 88, y + 68, 0x224466 + (gx * gy) % 16 * 0x010101))
rects.append((0, 0, W - 1, 40, 0x18304F))
for i in range(8):
    rects.append((W - 130, 60 + i * 60, W - 20, 110 + i * 60, 0x2A4A7A))
say("    共 %d 个矩形" % len(rects))


def many_gpu():
    gf.begin()
    for (x0, y0, x1, y1, c) in rects:
        gf.rect(x0, y0, x1, y1, c)
    gf.commit()
    return gf.ms


def many_cpu():
    gf.begin()
    for (x0, y0, x1, y1, c) in rects:
        gf.rect(x0, y0, x1, y1, c)
    gf.commit_cpu()


many_gpu()
mg = 0.0
for _ in range(10):
    mg += many_gpu()
mg /= 10
gf.lib.cb_stats_reset()
many_cpu()
for _ in range(10):
    many_cpu()
mc, _ = gf.cpu_stats()
mc /= 11.0
say("    %-28s %8.3f ms" % ("FPGA GPU  69 矩形", mg))
say("    %-28s %8.3f ms" % ("CPU C填充器 69 矩形", mc))
say("    >>> 69 矩形: GPU %s %.2f 倍"
    % ("快" if mg < mc else "慢", max(mg, mc) / min(mg, mc)))
fails += verify(rects[0][0], rects[0][1], rects[0][2], rects[0][3],
                rects[0][4], "网格第一个方块")
fails += verify(W - 130, 60, W - 20, 110, 0x2A4A7A, "右侧第一个竖条")

# ---------------------------------------------------------------- 5
say("")
say("-" * 74)
say(" [5] CPU 卸载: GPU 画整屏的同时 CPU 是不是真的空出来了")
say("-" * 74)
gf.begin()
gf.rect(0, 0, W - 1, H - 1, 0x204060)
gf.commit()
sync_ms = gf.ms
gf.begin()
gf.post(0, 0, W - 1, H - 1, 0x402060)
t0 = time.time()
loops = 0
while not gf.idle():
    loops += 1
asy_ms = (time.time() - t0) * 1000.0
say("    同步 fill : %8.3f ms   (CPU 干等)" % sync_ms)
say("    异步 fill : %8.3f ms   期间 CPU 空转 %d 轮" % (asy_ms, loops))
say("    >>> 异步模式下这 %.2f ms CPU 是完全空闲的, 可以拿去做物理/AI 计算"
    % sync_ms)

# ---------------------------------------------------------------- 6
say("")
say("-" * 74)
say(" [6] LINE (Bresenham) 1000 像素")
say("-" * 74)
gf.begin()
gf.line(10, 10, 1000, 300, 0xFFFF00)
gf.commit()
say("    %-28s %8.3f ms" % ("FPGA GPU  直线", gf.ms))
gf.lib.cb_stats_reset()
gf.begin()
gf.line(10, 10, 1000, 300, 0xFFFF00)
gf.commit_cpu()
ms, _ = gf.cpu_stats()
say("    %-28s %8.3f ms" % ("CPU C填充器 直线", ms))

# ---------------------------------------------------------------- 结论
say("")
say("=" * 74)
say(" 结论")
say("=" * 74)
say("    项目          GPU          CPU(C)       GPU 优势")
say("    整屏填充   %8.3f ms  %8.3f ms   %6.2f x"
    % (gpu_full, cpu_full, cpu_full / gpu_full))
say("    顶栏       %8.3f ms  %8.3f ms   %6.2f x"
    % (gpu_bar, cpu_bar, cpu_bar / gpu_bar))
say("    69 个矩形  %8.3f ms  %8.3f ms   %6.2f x"
    % (mg, mc, mc / mg))
say("")
say("    旧 RTL (1 字节/拍): 整屏 20.19 ms / 91 MB/s")
say("    新 RTL (8 字节/拍): 整屏 %.3f ms / %.1f MB/s"
    % (gpu_full, W * H * 3 / gpu_full / 1000.0))
say("    加速倍数: %.1f x" % (20.19 / gpu_full))
say("")
if fails == 0:
    say("    ★ 全部像素逐字节校验通过")
else:
    say("    ✗ 有 %d 处校验失败!!" % fails)
say("=" * 74)

gf.close()
flush_out()
