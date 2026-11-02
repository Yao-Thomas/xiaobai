#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_state.py —— 板子音频链路的真实状态 (别拿 -517 当结论, 那是 EPROBE_DEFER)"""
import io
import socket
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"

CMD = r'''
echo "### 声卡列表 (最权威)"; cat /proc/asound/cards 2>&1
echo; echo "### /dev/snd"; ls -l /dev/snd/ 2>&1
echo; echo "### aplay -l"; aplay -l 2>&1 | head -20
echo; echo "### arecord -l"; arecord -l 2>&1 | head -20
echo; echo "### codec 注册情况"; ls /proc/asound/card*/ 2>&1
for c in /proc/asound/card*/codec*; do [ -f "$c" ] && echo "--- $c ---" && head -4 "$c"; done
echo; echo "### dmesg 里音频相关 (全量, 不 tail)"; dmesg | grep -iE "wm8960|asoc|snd|i2s|audio|codec" 2>&1
echo; echo "### 音频相关模块在不在"; ls /lib/modules/$(uname -r)/kernel/sound/soc/codecs/ 2>&1 | head -30
echo "--- extra ---"; ls /lib/modules/$(uname -r)/extra/ 2>&1
echo "--- 全盘找 wm8960 ---"; find /lib/modules -iname "*wm8960*" 2>&1
echo; echo "### DTB 里声音节点"; ls /proc/device-tree/ 2>&1 | tr '\n' ' '; echo
for d in /proc/device-tree/*ound* /proc/device-tree/*audio*; do [ -e "$d" ] && echo "== $d"; done
echo; echo "### 内核里编进去的 snd 部分 (看 config)"; zcat /proc/config.gz 2>/dev/null | grep -iE "SND_SOC_WM8960|SND_SOC_ZYNQ|SND_SOC_XILINX|SND_SIMPLE_CARD|SND_SOC_I2S" || echo "(没有 /proc/config.gz)"
'''


def main():
    board.HOST = board.find_host(verbose=False)
    print("HOST =", board.HOST)
    if not board.HOST:
        return 1
    out, _ = broot.srun(CMD, timeout=180, quiet=True)
    print(out)
    open(r"D:\ubuntu_iso\audio_state.txt", "w", encoding="utf8").write(out)
    return 0


sys.exit(main())
