#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_diag.py —— 在 arecord 运行中读 formatter 的 S2MM 配置

背景：
  - 硬件要求 S24_LE / SAMPLE_BITS=32 / FRAME_BITS=64
  - 但采集出来是全零或垃圾（右声道 65535/65534 满量程翻转）
  - Codex 修放音时发现：formatter 综合成 PCM→AES，需要"32 位旁路"
    才能出正常声音。采集侧可能没做同样的处理。

要做的事：arecord 跑起来之后，读两边的 formatter 控制寄存器，
对比 MM2S（放音，已知正常）和 S2MM（采集，疑似有问题）的位宽字段。
"""
import subprocess
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from audio_pl import Mem, FMT_BASE                            # noqa: E402

BIT_DEPTH = {0: 8, 1: 16, 2: 20, 3: 24, 4: 32}
DW_SHIFT = 16


def main():
    m = Mem()
    print("=" * 78)
    print("采集路径的 formatter 配置（arecord 运行中读）")
    print("=" * 78)

    # 不采集时的基线
    print()
    print("--- 1) 不采集时 ---")
    for tag, base in (("MM2S(放音)", 0x100), ("S2MM(采集)", 0x000)):
        for off, name in ((0x00, "CTRL"), (0x04, "STS")):
            try:
                v = m.rd(FMT_BASE, base + off)
                dw = (v >> DW_SHIFT) & 0x7
                print("  %-12s %-5s (0x%03X) = 0x%08X   位宽字段=%d(%sbit)  DMA_EN=%d"
                      % (tag, name, base + off, v, dw,
                         BIT_DEPTH.get(dw, "?"), v & 1))
            except Exception as e:
                print("  %-12s %-5s 读失败: %s" % (tag, name, e))
    # CORE_CONFIG
    try:
        cfg = m.rd(FMT_BASE, 0x00)
        print("  CORE_CONFIG (0x000) = 0x%08X  mode=%d(%s)"
              % (cfg, (cfg >> 13) & 3,
                 {0: "AES->AES", 1: "AES->PCM", 2: "PCM->PCM",
                  3: "PCM->AES"}.get((cfg >> 13) & 3, "?")))
    except Exception as e:
        print("  CORE_CONFIG 读失败:", e)

    # 启动 arecord
    print()
    print("--- 2) 启动 arecord 采集 3 秒，采集期间读 ---")
    p = subprocess.Popen(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-r", "44100",
         "-c", "2", "-d", "3", "/tmp/capdiag.wav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    for k in range(3):
        print("  第 %d 次:" % (k + 1))
        for tag, base in (("MM2S", 0x100), ("S2MM", 0x000)):
            try:
                v = m.rd(FMT_BASE, base + 0x00)
                dw = (v >> DW_SHIFT) & 0x7
                x = m.rd(FMT_BASE, base + 0x28)
                print("    %-5s CTRL=0x%08X 位宽=%d(%sbit) DMA_EN=%d   XFER=0x%08X"
                      % (tag, v, dw, BIT_DEPTH.get(dw, "?"), v & 1, x))
            except Exception as e:
                print("    %-5s 读失败 %s" % (tag, e))
        time.sleep(0.6)
    p.wait()
    print("  arecord 退出码:", p.returncode)

    # 采集结果
    print()
    print("--- 3) 采集到的数据 ---")
    import wave, struct
    try:
        w = wave.open("/tmp/capdiag.wav", "rb")
        n, sw = w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
        w.close()
        v = list(struct.unpack("<%di" % (len(raw) // 4), raw))
        uniq = len(set(v))
        pk = max(abs(x) for x in v) if v else 0
        print("  %d 帧  位宽=%dbit  不同取值=%d  峰值=%.3f%% 满量程"
              % (n, sw * 8, uniq, pk / 2147483647.0 * 100))
        print("  前 16 个: %s" % ["0x%08X" % (x & 0xFFFFFFFF) for x in v[:16]])
        # 低 8 位统计（左对齐的话低 8 位应该全 0）
        low = sum(1 for x in v[:5000] if (x & 0xFF) != 0)
        print("  前 5000 个里低 8 位非零的: %d  (若≈0 说明数据是左对齐 24bit)" % low)
        hi = sum(1 for x in v[:5000] if (x >> 24) != 0)
        print("  前 5000 个里高 8 位非零的: %d" % hi)
    except Exception as e:
        print("  读采集结果失败:", e)

    m.close()
    print()
    print("★ 判读：")
    print("  * MM2S 位宽字段应该是 4(32bit) —— Codex 放音修好的状态")
    print("  * 若 S2MM 位宽字段不是 4，或两边不一致 -> 采集侧没做 32 位旁路")
    return 0


if __name__ == "__main__":
    sys.exit(main())
