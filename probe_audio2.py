#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_audio2.py —— 深挖: codec 到底绑没绑 + ASOC 里有哪些 DAI + 装 alsa-utils"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### A) wm8960 (i2c 1-001a) 绑定情况"
ls -l /sys/bus/i2c/devices/1-001a/ 2>&1
echo -n "name = "; cat /sys/bus/i2c/devices/1-001a/name 2>&1
echo -n "driver = "; readlink -f /sys/bus/i2c/devices/1-001a/driver 2>&1
echo "--- i2c 上已注册的驱动 ---"
ls /sys/bus/i2c/drivers/ 2>&1
echo "--- wm8960 驱动目录里挂了哪些设备 ---"
ls /sys/bus/i2c/drivers/wm8960/ 2>&1
echo
echo "### B) 内核里 wm8960 驱动在不在"
ls /sys/module/ 2>/dev/null | grep -i -E "wm8960|snd" 
echo "--- config 确认 ---"
zcat /proc/config.gz 2>/dev/null | grep -iE "WM8960|SND_SOC_XILINX|PL_SND_CARD|SND_SOC_I2S" || echo "(无 /proc/config.gz)"
echo
echo "### C) 挂 debugfs 看 ASOC / clk"
mount -t debugfs none /sys/kernel/debug 2>&1
echo "--- /sys/kernel/debug/asoc ---"
ls -R /sys/kernel/debug/asoc 2>&1 | head -40
echo "--- clk_summary 里的 mclk / clk_wiz ---"
grep -iE "mclk|clk_wiz|43c3" /sys/kernel/debug/clk/clk_summary 2>&1 | head -20
echo
echo "### D) dmesg 全文里的 clk / i2c / deferred"
dmesg | grep -iE "defer|clk|i2c-1|1-001a|wm8960|asoc|snd" 2>&1 | head -40
echo
echo "### E) 设备树 wm8960 的 clocks 指向"
python3 - <<'PY'
import struct, os
def rd(p):
    try: return open(p,'rb').read()
    except Exception: return b''
b = rd('/proc/device-tree/amba/i2c@e0004000/wm8960@1a/clocks')
print("  clocks 原始:", b.hex(' '), "->", [struct.unpack('>I', b[i:i+4])[0] for i in range(0,len(b)-3,4)])
b = rd('/proc/device-tree/amba/i2c@e0004000/wm8960@1a/clock-names')
print("  clock-names:", b)
b = rd('/proc/device-tree/amba_pl/clk_wiz@43c30000/phandle')
print("  clk_wiz phandle:", struct.unpack('>I', b)[0] if len(b)==4 else b)
b = rd('/proc/device-tree/amba/i2c@e0004000/status')
print("  i2c@e0004000 status:", b or b'(无, 默认okay)')
PY
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)

    print("### F) 装 alsa-utils (播放/录音工具, 板子上没有)")
    broot.srun("apt-get update -qq 2>&1 | tail -3; "
               "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq alsa-utils 2>&1 | tail -8; "
               "which aplay arecord amixer; aplay -l 2>&1 | head", timeout=900)


main()
