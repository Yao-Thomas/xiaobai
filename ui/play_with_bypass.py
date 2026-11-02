#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""play_with_bypass.py —— 播放中读 MM2S_CTRL，必要时强制 32 位旁路

Codex 的手动成功靠 "formatter 32 位旁路"（MM2S_CTRL 位宽字段 4）。
先看驱动现在有没有设对；没设对就手动补上。

用法: sudo python3 play_with_bypass.py <wav> [force]
"""
import mmap
import os
import struct
import subprocess
import sys
import time

BASE = 0x43C50000
MM2S_CTRL = 0x110
DW_SHIFT = 16
BIT_DEPTH = {0: 8, 1: 16, 2: 20, 3: 24, 4: 32}


def main():
    wav = sys.argv[1] if len(sys.argv) > 1 else "/home/zynq/Music/提示音.wav"
    force = "force" in sys.argv

    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    mem = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                    mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)

    def rd(off):
        return struct.unpack("<I", mem[off:off + 4])[0]

    def wr(off, v):
        mem[off:off + 4] = struct.pack("<I", v)

    print("=" * 76)
    print("播放 + MM2S 位宽旁路检查")
    print("=" * 76)
    print("  空闲: MM2S_CTRL = 0x%08X  位宽=%d(%sbit)"
          % (rd(MM2S_CTRL), (rd(MM2S_CTRL) >> DW_SHIFT) & 7,
             BIT_DEPTH.get((rd(MM2S_CTRL) >> DW_SHIFT) & 7, "?")))
    print()
    print("  播放 %s" % wav)
    sys.stdout.flush()

    p = subprocess.Popen(["aplay", "-q", wav],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)

    v = rd(MM2S_CTRL)
    dw = (v >> DW_SHIFT) & 7
    print("  播放中: MM2S_CTRL = 0x%08X  位宽=%d(%sbit)  DMA_EN=%d"
          % (v, dw, BIT_DEPTH.get(dw, "?"), v & 1))
    if dw == 4:
        print("    -> 驱动已经设成 32 位旁路了")
    else:
        print("    -> ★ 驱动没设对（应该是 4），手动补上")
        wr(MM2S_CTRL, (v & ~(7 << DW_SHIFT)) | (4 << DW_SHIFT))
        print("       写入后 = 0x%08X 位宽=%d"
              % (rd(MM2S_CTRL), (rd(MM2S_CTRL) >> DW_SHIFT) & 7))

    if force:
        print("  [force] 每 0.25 秒持续纠正位宽")
        for _ in range(40):
            cur = rd(MM2S_CTRL)
            if ((cur >> DW_SHIFT) & 7) != 4:
                wr(MM2S_CTRL, (cur & ~(7 << DW_SHIFT)) | (4 << DW_SHIFT))
            time.sleep(0.25)

    # 播放中反复打印状态
    for k in range(8):
        v = rd(MM2S_CTRL)
        print("    t=%.1fs  MM2S_CTRL=0x%08X 位宽=%d"
              % (0.4 + k * 0.5, v, (v >> DW_SHIFT) & 7))
        time.sleep(0.5)

    p.wait()
    print("  aplay 退出码:", p.returncode)
    mem.close()
    os.close(fd)
    print()
    print("★ 判读：若播放中位宽=4 且你仍听不到，说明旁路不是这次的根因。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
