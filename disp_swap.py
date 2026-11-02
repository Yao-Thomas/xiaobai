#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""disp_swap.py —— 换 bitstream 后把显示流水线恢复回来

背景:
  PL 重新配置后, 显示相关的 IP 全部回到复位值, DRM 驱动当初写进去的工作
  寄存器丢了, 所以屏幕黑/冻。
  clk_wiz (像素时钟 MMCM) 不用管: 它的配置是 bitstream 自带的, 我们的设计
  就是原厂设计 + GPU, 所以重配后自动锁回同样的频率。
  ★ 千万不要去写 clk_wiz 的寄存器! 写坏会让 PL 总线挂死, 整个内核卡住
    (这个坑已经踩过)。

只恢复这两个:
  lcd_vtc     0x43C10000   时序发生器
  lcd_frmbuf  0x43C20000   帧缓冲读 DMA

用法:
    python3 disp_swap.py save       # 显示正常时抓快照
    python3 disp_swap.py load [名字] # 用 FPGA Manager 换 bitstream
    python3 disp_swap.py restore    # 写回 VTC + frmbuf
    python3 disp_swap.py dump       # 看当前寄存器
    python3 disp_swap.py onestep    # 一条龙: save -> load -> restore
"""
import json
import mmap
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ★ 只碰这两个, 绝对不碰 clk_wiz
RESTORE_REGIONS = [
    ("lcd_vtc",    0x43C10000),
    ("lcd_frmbuf", 0x43C20000),
]
# 只读记录用, 不写回
READONLY_REGIONS = [
    ("lcd_id",  0x41200000),
    ("lcd_pwm", 0x43C00000),
    ("clk_wiz", 0x43C30000),
]
N = 64
SNAP = "/home/zynq/disp_snap.json"
MGR = "/sys/class/fpga_manager/fpga0"


def rd(addr, n):
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=addr)
        vals = [struct.unpack_from("<I", m, i * 4)[0] for i in range(n)]
        m.close()
        return vals
    finally:
        os.close(fd)


def wr(addr, vals):
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=addr)
        for i, v in enumerate(vals):
            m[i * 4:i * 4 + 4] = struct.pack("<I", v & 0xFFFFFFFF)
        m.close()
    finally:
        os.close(fd)


def show(name, addr, n=12):
    try:
        vals = rd(addr, n)
        print("  %-11s @0x%08X: %s" % (name, addr, " ".join("%08X" % v for v in vals)))
    except Exception as e:
        print("  %-11s @0x%08X: ✗ %s" % (name, addr, e))


def do_save():
    snap = {}
    print("读可写区 (会被写回):")
    for name, addr in RESTORE_REGIONS:
        vals = rd(addr, N)
        snap[name] = {"addr": addr, "vals": vals}
        nz = sum(1 for v in vals if v)
        print("  %-11s @0x%08X  非零 %2d/%d   前8个: %s"
              % (name, addr, nz, N, " ".join("%08X" % v for v in vals[:8])))
    snap["_readonly"] = {}
    print("读只读区 (仅记录, 不写回):")
    for name, addr in READONLY_REGIONS:
        try:
            vals = rd(addr, N)
            snap["_readonly"][name] = {"addr": addr, "vals": vals}
            print("  %-11s @0x%08X  前8个: %s"
                  % (name, addr, " ".join("%08X" % v for v in vals[:8])))
        except Exception as e:
            print("  %-11s @0x%08X  ✗ %s" % (name, addr, e))
    with open(SNAP, "w") as f:
        json.dump(snap, f)
    print("已保存 -> %s" % SNAP)


def do_load(fname):
    src = "/home/zynq/" + fname
    if os.path.exists(src):
        os.system("cp -f %s /lib/firmware/gpu.bin" % src)
        print("  拷贝 %s -> /lib/firmware/gpu.bin" % src)
    t0 = time.time()
    with open(MGR + "/flags", "w") as f:
        f.write("0")
    with open(MGR + "/firmware", "w") as f:
        f.write("gpu.bin")
    st = open(MGR + "/state").read().strip()
    print("  加载完成 state=%s  (%.2f 秒)" % (st, time.time() - t0))


def do_restore():
    snap = json.load(open(SNAP))
    for name, addr in RESTORE_REGIONS:
        if name not in snap:
            continue
        vals = snap[name]["vals"]
        wr(addr, vals)
        print("  %-11s @0x%08X  已写回 %d 个寄存器" % (name, addr, len(vals)))
    print("写回完成")


def do_dump():
    print("可写区:")
    for name, addr in RESTORE_REGIONS:
        show(name, addr)
    print("只读区:")
    for name, addr in READONLY_REGIONS:
        show(name, addr)


def do_onestep(fname):
    print("=== 1) 抓快照 (当前显示应该是正常的) ===")
    do_save()
    print()
    print("=== 2) 换 bitstream ===")
    do_load(fname)
    print()
    print("=== 3) 换完后的寄存器 (应该全变复位值) ===")
    do_dump()
    print()
    print("=== 4) 写回显示流水线寄存器 ===")
    do_restore()
    print()
    print("=== 5) 写回后的寄存器 (应该跟快照一致) ===")
    do_dump()
    print()
    print("=== 6) GPU 在不在 ===")
    os.system("cd /home/zynq/ui && python3 gpu_probe.py")
    print()
    print("=== 7) 桌面状态 (没停过, 应该还在跑) ===")
    os.system("systemctl is-active zynq-desktop")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"
    arg = sys.argv[2] if len(sys.argv) > 2 else "gpu2026_swapped.bin"
    if cmd == "save":
        do_save()
    elif cmd == "load":
        do_load(arg)
    elif cmd == "restore":
        do_restore()
    elif cmd == "dump":
        do_dump()
    elif cmd == "onestep":
        do_onestep(arg)
    else:
        print(__doc__)
