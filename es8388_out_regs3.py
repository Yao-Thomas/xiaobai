#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""es8388_out_regs.py —— 按**正确的十进制编号**挖输出级寄存器

★ 关键纠正：手册正文用**十进制**编号！
    "Register 26 – DAC Control 4" 里的 LDACVOL 就是代码里的 0x1A
    所以：
        手册 Register N   ->  实际 I2C 地址 0xNN（N<10）或 0x1N（N>=16）
        更准确：手册 Register 26 = 0x1A,  27 = 0x1B,  30 = 0x1E,  31 = 0x1F
                手册 Register 46 = 0x2E,  47 = 0x2F,  48 = 0x30,  49 = 0x31

我们要查的（走喇叭的输出通路）:
    Register 38~45 (0x26~0x2D) —— 输出混合器 / 其他
    Register 46~49 (0x2E~0x31) —— LOUT1/ROUT1/LOUT2/ROUT2 音量
"""
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
     r"\7_芯片数据手册\19_音频编解码芯片\es8388.pdf")

doc = fitz.open(P)
full = "\n".join(doc[i].get_text() for i in range(doc.page_count))

# 手册里寄存器小结从 "Register NN –" 开始，到下一个 "Register NN –" 结束
blocks = re.split(r"(?=Register\s+\d+\s*[-–—])", full)

WANT = list(range(44, 52))          # 十进制 44..51 -> 0x2C..0x33
print("=" * 88)
print("按十进制编号提取（手册 Register 26..49 = 实际 0x1A..0x31）")
print("=" * 88)
for b in blocks:
    m = re.match(r"Register\s+(\d+)\s*[-–—]\s*([^\n]*)", b)
    if not m:
        continue
    num = int(m.group(1))
    if num not in WANT:
        continue
    # 跳过目录页那几行（很短且带 "...."）
    if "...." in b[:120]:
        continue
    hexa = "0x%02X" % num
    body = b[:2000]
    print()
    print("### 手册 Register %d  ==  实际地址 %s" % (num, hexa))
    print(body.strip()[:1300])
    print("-" * 88)
