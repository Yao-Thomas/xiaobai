#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_audio3.py —— 挂 debugfs 看 ASOC/clk, 取完整 dmesg, 并试着手动 bind codec"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### A) 挂 debugfs"
mkdir -p /sys/kernel/debug
mount -t debugfs none /sys/kernel/debug 2>&1
ls /sys/kernel/debug/ 2>&1 | head
echo
echo "### B) clk_summary 里的 mclk"
grep -iE "mclk|clk_wiz|43c3|lcd_pclk" /sys/kernel/debug/clk/clk_summary 2>&1 | head -20
echo "--- 所有 clk_wiz 输出 ---"
grep -iE "wizard|clk_wiz" /sys/kernel/debug/clk/clk_summary 2>&1 | head -20
echo
echo "### C) ASOC 里注册了哪些组件"
ls -R /sys/kernel/debug/asoc 2>&1 | head -50
echo
echo "### D) 完整 dmesg (前 200 行里和音频/clk 有关的)"
dmesg 2>&1 | head -200
echo
echo "### E) 试着手动 bind wm8960"
echo 1-001a > /sys/bus/i2c/drivers/wm8960/bind 2>&1
sleep 1
echo -n "bind 后 driver = "; ls -l /sys/bus/i2c/devices/1-001a/driver 2>&1
echo "--- 驱动目录 ---"; ls /sys/bus/i2c/drivers/wm8960/ 2>&1
echo "--- dmesg 尾部 ---"; dmesg 2>&1 | tail -15
echo
echo "### F) 再看看 clk_wiz 的 clk 提供者"
ls /sys/kernel/debug/clk/ 2>&1 | head
'''


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)


main()
