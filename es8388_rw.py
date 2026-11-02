#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_rw.py —— 直接读写 ES8388 寄存器（绕过内核驱动的占用）

为什么需要这个
--------------
ES8388 的 I2C 地址 0x10 被内核的 es8388 驱动占着，所以：
  · i2cget/i2cset 报 "Could not set address to 0x10: Device or resource busy"
  · 自己 open("/dev/i2c-1") + ioctl(I2C_SLAVE) 也报同样的错

用的是 Linux i2c-dev 的另一个 ioctl：
    I2C_SLAVE       = 0x0703   普通，会检查占用
    I2C_SLAVE_FORCE = 0x0706   ★ 跳过检查，强制选中

这样就不用去 sysfs 卸载驱动再装回来（那样容易把声卡搞坏）。

注意：驱动可能在某些时刻重写寄存器。如果写完没效果，
      就开着录音持续写（见 cap_diag 的思路）。

用法:
    sudo python3 es8388_rw.py dump                # dump 关键寄存器
    sudo python3 es8388_rw.py rd 0x0A             # 读一个
    sudo python3 es8388_rw.py wr 0x0A 0x00        # 写一个
    sudo python3 es8388_rw.py mic                 # 一键切到麦克风输入
    sudo python3 es8388_rw.py line                # 一键切回 LINE 输入
"""
import fcntl
import os
import sys

I2C_SLAVE_FORCE = 0x0706
BUS = 1
ADDR = 0x10

NAMES = {
    0x00: "Chip Ctrl 1", 0x01: "Chip Ctrl 2", 0x02: "Chip Power",
    0x03: "ADC Power  ★PdnMICB", 0x04: "DAC Power", 0x05: "Chip Low Pwr",
    0x06: "Chip Low Pwr2", 0x07: "Analog Volume", 0x08: "Master Mode",
    0x09: "ADC Ctrl 1", 0x0A: "ADC Ctrl 2  ★★输入选择", 0x0B: "DAC Ctrl 1",
    0x0C: "DAC Ctrl 2", 0x0D: "ADC Ctrl 5  ★", 0x0E: "ADC Ctrl 6",
    0x0F: "ADC Ctrl 7", 0x10: "DAC Ctrl 3", 0x11: "DAC Ctrl 4",
    0x12: "DAC Ctrl 5", 0x13: "DAC Ctrl 6", 0x14: "DAC Ctrl 7",
    0x15: "DAC Ctrl 8", 0x16: "DAC Ctrl 9", 0x17: "ADC Ctrl 3  ★",
    0x18: "ADC Ctrl 4", 0x19: "ADC PGA L  ★", 0x1A: "ADC PGA R  ★",
    0x1B: "ADC ALC 1", 0x1C: "ADC ALC 2", 0x1D: "DAC Ctrl 8",
    0x1E: "DAC Ctrl 9", 0x1F: "DAC Ctrl 10", 0x20: "DAC Ctrl 11",
    0x21: "DAC Ctrl 12", 0x22: "DAC Ctrl 13", 0x23: "DAC Ctrl 14",
    0x24: "DAC Ctrl 15", 0x25: "DAC Ctrl 16", 0x26: "DAC Ctrl 17",
    0x27: "DAC Ctrl 18", 0x28: "DAC Ctrl 19", 0x29: "DAC Ctrl 20",
    0x2A: "DAC Ctrl 21", 0x2B: "DAC Ctrl 22", 0x2C: "DAC Ctrl 23",
    0x2D: "DAC Ctrl 24", 0x2E: "Output 1 L", 0x2F: "Output 1 R",
    0x30: "Output 2 L", 0x31: "Output 2 R",
}

# ADC 输入选择（寄存器 0x0A 低 2 位）
INPUT_MIC = 0x00        # LIN1/RIN1 -> 麦克风
INPUT_LINE = 0x01       # LIN2/RIN2 -> LINE IN
INPUT_DIFF = 0x02       # 差分

# 从上一轮 main_cnn5 / cap_adc_fix.py 里记录的"老代码能录音"的值
GOOD_MIC = [(0x03, 0x51), (0x0A, 0x00), (0x0D, 0x02)]
# 驱动当前的（对照/恢复）
DRV_LINE = [(0x03, 0x09), (0x0A, 0x50), (0x0D, 0x03)]


class Codec(object):
    def __init__(self, bus=BUS, addr=ADDR):
        self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
        # ★ 用 FORCE，跳过"设备忙"检查
        fcntl.ioctl(self.fd, I2C_SLAVE_FORCE, addr)
        self.addr = addr

    def rd(self, reg):
        os.write(self.fd, bytes([reg & 0xFF]))
        return os.read(self.fd, 1)[0]

    def wr(self, reg, val):
        os.write(self.fd, bytes([reg & 0xFF, val & 0xFF]))

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root: sudo python3 %s" % os.path.basename(__file__))

    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"
    c = Codec()
    try:
        if cmd == "dump":
            print("=" * 70)
            print(" ES8388 dump  (i2c-%d @ 0x%02X, 用 I2C_SLAVE_FORCE)" % (BUS, ADDR))
            print("=" * 70)
            keys = [0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x09, 0x0A, 0x0B,
                    0x0C, 0x0D, 0x0E, 0x10, 0x11, 0x12, 0x17, 0x18, 0x19,
                    0x1A, 0x1B, 0x1C, 0x1D, 0x26, 0x27, 0x2E, 0x30]
            for r in keys:
                v = c.rd(r)
                mark = ""
                if r == 0x0A:
                    lo = v & 0x03
                    mark = {0: "  <- 低2位=%d MIC(LIN1/RIN1)" % lo,
                            1: "  <- 低2位=%d LINE(LIN2/RIN2)" % lo,
                            2: "  <- 低2位=差分"}.get(lo, "")
                if r == 0x03:
                    mark = "  <- bit3 PdnMICB=%d bit2 PdnADCB=%d" % (
                        (v >> 3) & 1, (v >> 2) & 1)
                print("  0x%02X  %-24s = 0x%02X%s" % (r, NAMES.get(r, ""), v, mark))

        elif cmd == "rd":
            r = int(sys.argv[2], 0)
            print("0x%02X = 0x%02X" % (r, c.rd(r)))

        elif cmd == "wr":
            r = int(sys.argv[2], 0)
            v = int(sys.argv[3], 0)
            old = c.rd(r)
            c.wr(r, v)
            new = c.rd(r)
            print("0x%02X: 0x%02X -> 写入 0x%02X -> 读回 0x%02X  %s"
                  % (r, old, v, new, "✓" if new == v else "★ 没写进去（驱动覆盖了？）"))

        elif cmd in ("mic", "line"):
            tbl = GOOD_MIC if cmd == "mic" else DRV_LINE
            print("切换到 %s 输入：" % ("麦克风" if cmd == "mic" else "LINE"))
            for r, v in tbl:
                old = c.rd(r)
                c.wr(r, v)
                new = c.rd(r)
                print("  0x%02X %-22s 0x%02X -> 0x%02X  %s"
                      % (r, NAMES.get(r, ""), old, new,
                         "✓" if new == v else "★ 被改回"))
        else:
            print("未知命令: %s" % cmd)
    finally:
        c.close()


if __name__ == "__main__":
    main()
