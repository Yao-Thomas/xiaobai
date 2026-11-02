#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_probe.py —— 查板子上的音频采集（WM8960）能不能当示波器输入"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

SCRIPT = r'''
echo "=== ALSA 声卡 ==="
cat /proc/asound/cards 2>/dev/null || echo "(没有 /proc/asound)"
echo
echo "=== 播放/采集设备 ==="
aplay -l 2>&1 | head -20
echo "---"
arecord -l 2>&1 | head -20
echo
echo "=== codec 名称 ==="
for c in /proc/asound/card*/codec*; do [ -f "$c" ] && echo "--- $c ---" && head -6 "$c"; done
echo
echo "=== 采集通道 (capture controls) ==="
CODEC=$(ls /proc/asound/card*/codec* 2>/dev/null | head -1)
if [ -n "$CODEC" ]; then
  grep -n -i -A3 "Capture" "$CODEC" | head -60
fi
echo
echo "=== 有没有 LINE_IN / MIC 相关的 kcontrol ==="
amixer -c 0 scontrols 2>/dev/null | head -30
echo "---"
amixer -c 0 scontents 2>/dev/null | grep -i -B1 -A2 "capture\|line\|mic" | head -50
echo
echo "=== I2S / audio_formatter 驱动 ==="
lsmod 2>/dev/null | grep -i -E "snd|i2s|audio|wm8960" 
dmesg 2>/dev/null | grep -i -E "wm8960|asoc|i2s|audio" | tail -15
'''

ALSO = r'''
echo "=== 试录 1 秒 (看能不能拿到数据) ==="
cd /tmp
timeout 10 arecord -D hw:0,0 -f S16_LE -r 48000 -c 2 -d 1 /tmp/_probe_cap.wav 2>&1 | tail -5
echo "RC=$?"
ls -l /tmp/_probe_cap.wav 2>/dev/null
if [ -f /tmp/_probe_cap.wav ]; then
  od -An -td2 -j 44 -N 64 /tmp/_probe_cap.wav | head -4
fi
'''


def root_run(script, tag, timeout=180):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    board.put(local, "/tmp/_%s.sh" % tag)
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_%s.sh" % (board.PASS, tag),
                       timeout=timeout)
    print(out)


if __name__ == "__main__":
    root_run(SCRIPT, "aud")
    if "--try" in sys.argv:
        root_run(ALSO, "audtry")
