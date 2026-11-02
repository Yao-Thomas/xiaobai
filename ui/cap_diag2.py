#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_diag2.py —— 修正偏移后，读 formatter 两侧的配置

★ 偏移（Xilinx Audio Formatter）：
    0x000  CORE_CONFIG     全局（含 mode: 2=PCM->PCM, 3=PCM->AES）
    0x010  S2MM CTRL       ★ 采集侧
    0x110  MM2S CTRL       ★ 放音侧（Codex 已知修好）
    0x018 / 0x118  FS_MULT
    0x028 / 0x128  XFER

上一版把 S2MM 的 CTRL 当成 0x000 读了，读的是 CORE_CONFIG，且输出中断。
"""
import struct
import subprocess
import sys
import time
import wave

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from audio_pl import Mem, FMT_BASE                            # noqa: E402

BIT_DEPTH = {0: 8, 1: 16, 2: 20, 3: 24, 4: 32}
DW_SHIFT = 16


def show(m, tag):
    def rd(off):
        try:
            return m.rd(FMT_BASE, off)
        except Exception as e:
            return "ERR(%s)" % str(e)[:30]
    out = []
    for name, off in (("CORE_CONFIG", 0x000), ("S2MM_CTRL", 0x010),
                      ("S2MM_FSMULT", 0x018), ("S2MM_XFER", 0x028),
                      ("MM2S_CTRL", 0x110), ("MM2S_FSMULT", 0x118),
                      ("MM2S_XFER", 0x128)):
        v = rd(off)
        if isinstance(v, int):
            dw = (v >> DW_SHIFT) & 0x7
            extra = ""
            if "CTRL" in name:
                extra = " 位宽=%d(%sbit) DMA_EN=%d" % (dw, BIT_DEPTH.get(dw, "?"), v & 1)
            if name == "CORE_CONFIG":
                extra = " mode=%d(%s)" % ((v >> 13) & 3,
                                          {0: "AES->AES", 1: "AES->PCM",
                                           2: "PCM->PCM", 3: "PCM->AES"}.get((v >> 13) & 3, "?"))
            out.append("  %-13s (0x%03X) = 0x%08X%s" % (name, off, v, extra))
        else:
            out.append("  %-13s (0x%03X) = %s" % (name, off, v))
    print("[%s]" % tag)
    for l in out:
        print(l)
    sys.stdout.flush()


def main():
    m = Mem()
    print("=" * 84)
    print("formatter 两侧配置对比（修正偏移）")
    print("=" * 84)
    print()
    show(m, "1) 不采集不播放（空闲）")
    print()

    print("2) 启动 arecord 采集 3 秒")
    sys.stdout.flush()
    p = subprocess.Popen(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-r", "44100",
         "-c", "2", "-d", "3", "/tmp/capdiag2.wav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    show(m, "   采集进行中")
    print()
    p.wait()
    print("   arecord 退出码: %s" % p.returncode)
    print()
    show(m, "3) 采集结束后")
    print()

    print("4) 采集到的数据")
    try:
        w = wave.open("/tmp/capdiag2.wav", "rb")
        n, sw = w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
        w.close()
        if sw == 4:
            v = list(struct.unpack("<%di" % (len(raw) // 4), raw))
            FULL = 2147483647.0
        else:
            v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
            FULL = 32767.0
        uniq = len(set(v))
        pk = max(abs(x) for x in v) if v else 0
        print("   %d 帧  位宽=%dbit  不同取值=%d  峰值=%.2f%% 满量程"
              % (n, sw * 8, uniq, pk / FULL * 100))
        low = sum(1 for x in v[:5000] if (x & 0xFF) != 0)
        print("   前5000个里 低8位非零=%d  高8位非零=%d"
              % (low, sum(1 for x in v[:5000] if (x >> 24) != 0)))
        print("   前8个: %s" % ["0x%08X" % (x & 0xFFFFFFFF) for x in v[:8]])
    except Exception as e:
        print("   读失败:", e)

    m.close()
    print()
    print("★ 判读：MM2S_CTRL 位宽应=4（Codex 已修好的放音状态）。")
    print("        若 S2MM_CTRL 位宽 != 4，就是采集侧没做 32 位旁路。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
