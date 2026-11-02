#!/bin/bash
python3 /tmp/mic_analyze.py 2>&1 | head -45
echo
echo "===== ADC 相关寄存器现状 ====="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import I2C
i = I2C()
rows = [
    (0x09, "ADC Control 1 = PGA 增益（麦克风放大倍数）"),
    (0x0A, "ADC Control 2 = 输入选择 LINSEL/RINSEL"),
    (0x0B, "ADC Control 3"),
    (0x03, "ADC 电源（bit5 PdnADCL）"),
    (0x10, "ADC 数字音量 L"),
    (0x11, "ADC 数字音量 R"),
]
for r, n in rows:
    print("  0x%02X = 0x%02X   %s" % (r, i.rd(r), n))
i.close()
PY