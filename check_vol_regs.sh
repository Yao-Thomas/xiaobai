#!/bin/bash
cd /home/zynq/ui
echo "=== ES8388 关键音量寄存器（现在是 30/33 档）==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import I2C
i = I2C()
rows = [
    (0x1A, "DAC 数字音量 L   (0x00=0dB最大, 0xC0=-96dB静音)"),
    (0x1B, "DAC 数字音量 R"),
    (0x2E, "LOUT1 音量 (走耳机)"),
    (0x2F, "ROUT1 音量 (走耳机)"),
    (0x30, "LOUT2 音量 ★走喇叭功放"),
    (0x31, "ROUT2 音量 ★走喇叭功放"),
    (0x04, "DAC 电源"),
    (0x27, "输出混合器 L (DAC->LOUT)"),
    (0x2A, "输出混合器 R (DAC->ROUT)"),
    (0x02, "芯片电源"),
    (0x2B, "slrck/DLL"),
]
for r, nm in rows:
    print("  0x%02X = 0x%02X   %s" % (r, i.rd(r), nm))
i.close()
print()
print("  满量程参考: 0x1A/0x1B 应为 0x00; 0x2E..0x31 应为 33(0x21) 才是最大")
PY
echo
echo "=== 功放 MD8002A 的增益电阻（原理图: R39=20K 输入, R40=20K 反馈）==="
echo "  MD8002A 典型 BTL 增益 Av = 2 * (Rf/Ri) = 2 * (20K/20K) = 2  = +6dB"
echo
echo "=== 找板子上有没有功放手册 ==="
find / -iname "*md8002*" -o -iname "*8002*.pdf" 2>/dev/null | head -5
echo "(空表示板子上没有)"
