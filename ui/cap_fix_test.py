#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_fix_test.py —— 验证"采集侧 32 位旁路"能不能救活录音

假设：
  放音侧 Codex 用 S2MM/MM2S 的"位宽字段=4(32bit)"绕过 AES 编码器，声音正常。
  实测采集侧 S2MM_CTRL 位宽字段=3(24bit) -> 采到全零/垃圾。
  若把采集侧也改成 4，应该能录到真实音频。

做法：arecord 跑起来之后，把 S2MM_CTRL 的位宽字段改成 4，看数据变不变。
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

S2MM_CTRL = 0x010
DW_SHIFT = 16


def data_stats(path):
    try:
        w = wave.open(path, "rb")
        n, sw = w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
        w.close()
        if sw == 4:
            v = list(struct.unpack("<%di" % (len(raw) // 4), raw))
            FULL = 2147483647.0
        else:
            v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
            FULL = 32767.0
        if not v:
            return "空"
        uniq = len(set(v))
        pk = max(abs(x) for x in v)
        rms = (sum(float(x) * x for x in v) / len(v)) ** 0.5
        return ("%d帧 位宽%d 不同取值=%d 峰值=%.1f%% RMS=%.0f(%.1fdBFS)"
                % (n, sw * 8, uniq, pk / FULL * 100, rms,
                   20 * __import__("math").log10(max(1e-9, rms / FULL))))
    except Exception as e:
        return "读失败: %s" % e


def main():
    m = Mem()
    print("=" * 80)
    print("验证采集侧 32 位旁路")
    print("=" * 80)

    # ---- A: 不改，直接录（对照）----
    print()
    print("--- A) 不改寄存器，直接录 2 秒（对照）---")
    subprocess.run(["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE",
                    "-r", "44100", "-c", "2", "-d", "2", "/tmp/fix_A.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("   ", data_stats("/tmp/fix_A.wav"))

    # ---- B: 采集期间把 S2MM 位宽字段改成 4 ----
    print()
    print("--- B) 采集期间把 S2MM 位宽字段改成 4（32 位旁路）---")
    p = subprocess.Popen(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-r", "44100",
         "-c", "2", "-d", "4", "/tmp/fix_B.wav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    v0 = m.rd(FMT_BASE, S2MM_CTRL)
    print("    改之前 S2MM_CTRL = 0x%08X  位宽=%d" % (v0, (v0 >> DW_SHIFT) & 7))
    v1 = (v0 & ~(0x7 << DW_SHIFT)) | (4 << DW_SHIFT)
    m.wr(FMT_BASE, S2MM_CTRL, v1)
    time.sleep(0.2)
    print("    写 0x%08X 后读回 = 0x%08X  位宽=%d"
          % (v1, m.rd(FMT_BASE, S2MM_CTRL),
             (m.rd(FMT_BASE, S2MM_CTRL) >> DW_SHIFT) & 7))
    time.sleep(0.3)
    # 每 0.5 秒来一次（驱动可能改回去）
    for k in range(6):
        cur = m.rd(FMT_BASE, S2MM_CTRL)
        if ((cur >> DW_SHIFT) & 7) != 4:
            m.wr(FMT_BASE, S2MM_CTRL, (cur & ~(0x7 << DW_SHIFT)) | (4 << DW_SHIFT))
        time.sleep(0.5)
    p.wait()
    print("    arecord 退出码:", p.returncode)
    print("   ", data_stats("/tmp/fix_B.wav"))

    # ---- C: 再来一次，改成 0（PCM 直通？）看有没有别的值更好 ----
    print()
    print("--- C) 只读确认最终状态 ---")
    for title, off in (("S2MM_CTRL", 0x010), ("CORE_CONFIG", 0x000),
                       ("MM2S_CTRL", 0x110)):
        v = m.rd(FMT_BASE, off)
        print("    %-12s = 0x%08X  位宽=%d mode=%d"
              % (title, v, (v >> DW_SHIFT) & 7, (v >> 13) & 3))

    m.close()
    print()
    print("★ 判读：")
    print("  A 全零/常量 & B 有明显 RMS -> **采集侧 32 位旁路就是解**")
    print("  两段都全零 -> 还有别的问题（时钟/路由/驱动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
