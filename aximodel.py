#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aximodel.py —— 用 Python 逐拍复刻新 gpu2d_axi.v 的 AXI 主控逻辑,
   验证: (1) 写进内存的字节 == 期望的 BGR 流
         (2) 绝不越界写 run 之外的内存
         (3) 每个突发 <=256 拍, 且不跨 4KB 边界
"""
import random, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MAXBEAT = 256


def ph_of_off(o):
    return {0: 0, 1: 2, 2: 1, 3: 0, 4: 2, 5: 1, 6: 0, 7: 2}[o]


def simulate(run_addr, npix, color, mem_lo, mem_hi):
    """返回 (写入字典, 突发列表, 错误列表)"""
    R = (color >> 16) & 0xFF
    G = (color >> 8) & 0xFF
    B = color & 0xFF
    chan = {0: B, 1: G, 2: R}

    off = run_addr & 7
    base = run_addr & ~7
    run_bytes = npix * 3
    ext_len = off + run_bytes
    nbeats_all = (ext_len + 7) >> 3

    phase = ph_of_off(off)
    beat_idx = 0
    beats_left = nbeats_all
    cur_addr = base

    wr = {}
    bursts = []
    errs = []

    guard = 0
    while beats_left > 0:
        guard += 1
        if guard > 100000:
            errs.append("死循环!")
            break
        room4k = (4096 - (cur_addr & 0xFFF)) >> 3
        cap = min(room4k, MAXBEAT)
        this_burst = min(beats_left, cap)
        awlen = ((this_burst & 0xFF) - 1) & 0xFF
        if this_burst < 1:
            errs.append("this_burst=0 @%08X" % cur_addr)
            break
        if this_burst > MAXBEAT:
            errs.append("突发 %d 拍 > 256" % this_burst)
        span_lo = cur_addr
        span_hi = cur_addr + this_burst * 8 - 1
        if (span_lo >> 12) != (span_hi >> 12):
            errs.append("突发跨 4KB: %08X..%08X" % (span_lo, span_hi))
        bursts.append((cur_addr, awlen + 1))

        for k in range(this_burst):
            pos0 = beat_idx * 8
            remain = ext_len - pos0
            nb = 8 if remain >= 8 else (remain & 0xF)
            full_msk = 0xFF if nb >= 8 else ((1 << nb) - 1)
            wstrb = (full_msk & (0xFF << off)) if beat_idx == 0 else full_msk
            wdata = 0
            for j in range(8):
                wdata |= chan[(phase + j) % 3] << (8 * j)
            a = cur_addr + k * 8
            for j in range(8):
                if (wstrb >> j) & 1:
                    ad = a + j
                    if not (mem_lo <= ad <= mem_hi):
                        errs.append("越界写 %08X" % ad)
                    wr[ad] = (wdata >> (8 * j)) & 0xFF
            phase = (phase + nb) % 3
            beat_idx += 1
            beats_left -= 1
        cur_addr += this_burst * 8

    if beat_idx != nbeats_all:
        errs.append("拍数不符 %d != %d" % (beat_idx, nbeats_all))
    return wr, bursts, errs


def check(run_addr, npix, color, verbose=False):
    R = (color >> 16) & 0xFF
    G = (color >> 8) & 0xFF
    B = color & 0xFF
    expect = {}
    for i in range(npix * 3):
        expect[run_addr + i] = (B, G, R)[i % 3]

    lo = run_addr
    hi = run_addr + npix * 3 - 1
    wr, bursts, errs = simulate(run_addr, npix, color, lo, hi)

    bad = []
    for ad, v in wr.items():
        if ad not in expect:
            bad.append(("多写", ad, v))
        elif expect[ad] != v:
            bad.append(("错值", ad, v, expect[ad]))
    for ad in expect:
        if ad not in wr:
            bad.append(("漏写", ad))
    bad += [("规则", e) for e in errs]

    if verbose or bad:
        print("A=%08X N=%-5d 拍=%d 突发数=%d" %
              (run_addr, npix, (run_addr & 7) + npix * 3 + 7 >> 3, len(bursts)))
        print("   突发: %s" % (bursts[:6],))
    if bad:
        print("   ✗ 问题 %d 个: %s" % (len(bad), bad[:8]))
        return False
    return True


def main():
    random.seed(20260925)
    color = 0x1E90FF
    fail = 0
    total = 0

    # --- 1. 真实工况: 帧缓冲 0x3F100000, 每行 1024 像素, 600 行 ---
    FB = 0x3F100000
    STRIDE = 3072
    print("=== 1. 真实帧缓冲 600 行 x 1024 像素 ===")
    t0 = None
    for y in range(600):
        A = FB + y * STRIDE
        total += 1
        if not check(A, 1024, color):
            fail += 1
    # 另两个 page
    for y in (0, 1, 300, 599):
        for pg in (1, 2):
            A = FB + pg * 600 * STRIDE + y * STRIDE
            total += 1
            if not check(A, 1024, color):
                fail += 1
    print("   %d 个用例, 失败 %d" % (total, fail))

    # --- 2. 随机小 run (模拟 LINE 的 1 像素段) ---
    print("=== 2. 随机小 run (1..40 像素, 随机地址/颜色) ===")
    sub = 0
    subfail = 0
    for _ in range(4000):
        A = random.randrange(0x3F100000, 0x3F100000 + 200000)
        N = random.randrange(1, 40)
        c = random.randrange(0x1000000)
        total += 1
        sub += 1
        if not check(A, N, c):
            fail += 1
            subfail += 1
            if subfail > 4:
                break
    print("   %d 个用例, 失败 %d" % (sub, subfail))

    # --- 3. 边界用例 ---
    print("=== 3. 边界: 4KB 边界附近 / 极端长度 ===")
    seq = []
    for A in (0, 1, 2, 3, 4, 5, 6, 7, 8, 4095, 4096, 4097):
        seq.append((A, 1, color))
        seq.append((A, 2, color))
        seq.append((A, 1024, color))
    for d in (-9, -8, -7, -1, 0, 1, 7, 8, 9):
        seq.append((0x1000 + d, 5, color))
        seq.append((0x1000 + d, 300, color))
    # 跨 4KB 的长 run
    seq.append((0x0FF0, 1024, color))
    seq.append((0x0FFC, 1024, color))
    seq.append((0x1FF0, 1024, color))
    for A, N, c in seq:
        total += 1
        if not check(A, N, c, verbose=(A in (0, 4095, 4096, 4097))):
            fail += 1

    print()
    print("=" * 56)
    if fail == 0:
        print("✅ 全部通过: %d 个用例, 0 失败" % total)
    else:
        print("❌ 失败 %d / %d" % (fail, total))
    print("=" * 56)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
