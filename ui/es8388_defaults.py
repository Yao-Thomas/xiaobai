#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ES8388 寄存器三态对比：复位默认值 / 厂家 es8388_init 之后 / ADC 上电之后。

这样能精确知道哪几个寄存器被改过，而不是靠猜。
"""
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import I2C, es8388_init                          # noqa: E402

REGS = list(range(0x00, 0x35))


def dump(i2c, note):
    out = {}
    for r in REGS:
        try:
            out[r] = i2c.rd(r)
        except Exception as e:
            out[r] = -1
    print("[dump] %s" % note)
    return out


def show(tag, d):
    for base in range(0, len(REGS), 8):
        row = REGS[base:base + 8]
        print("  %s %s" % (tag, " ".join("%02X:%02X" % (r, d[r]) for r in row)))


def main():
    i2c = I2C()

    a = dump(i2c, "当前状态（上一个脚本留下的）")

    # --- 芯片复位 ---
    i2c.wr(0x00, 0x80)
    time.sleep(0.05)
    i2c.wr(0x00, 0x00)
    time.sleep(0.05)
    b = dump(i2c, "★ 芯片复位后的出厂默认值")

    # --- 厂家初始化（只跑 es8388_init，不碰 ADC 那一半）---
    es8388_init(i2c)
    time.sleep(0.05)
    c = dump(i2c, "厂家 es8388_init 之后")

    print("\n================ 出厂默认 vs 厂家init ================")
    print("  寄存器  默认  厂家  说明")
    changed = []
    for r in REGS:
        mark = ""
        if b[r] != c[r]:
            mark = "  <== 被改了"
            changed.append(r)
        print("   0x%02X   0x%02X  0x%02X%s" % (r, b[r], c[r], mark))
    print("\n[summary] 厂家 init 一共改了 %d 个寄存器: %s"
          % (len(changed), " ".join("0x%02X" % r for r in changed)))

    # --- 再看 ADC 上电后 ---
    print("\n================ 现在把 bit3 拨回去看差异 ================")
    before = i2c.rd(0x03)
    i2c.wr(0x03, 0x51)
    time.sleep(0.02)
    print("  0x03: 0x%02X -> 0x%02X (bit3 清 0)" % (before, i2c.rd(0x03)))
    i2c.wr(0x03, before)

    i2c.close()


if __name__ == "__main__":
    main()
