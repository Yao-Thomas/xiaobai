#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_audio_pins.py —— 核对 XDC 的音频引脚 vs V3.9 原理图

Codex 交接里的第 3 条建议：
  "查 V3.9 板原理图上 ES8388 的 BCLK、DACLRC、ADCLRC 与 FPGA 引脚是否真的与 XDC 一致。
   当前 XDC：aud_bclk=M18、aud_daclrc=G18、aud_adclrc=L20"

做法：从原理图 PDF 抽文字+坐标，找这 6 个引脚号出现在哪个网络附近，
      看是不是真的接在 ES8388 的对应信号上。
"""
import os
import re
import sys

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料"
       r"\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\3_开发板原理图和硬件相关文件\领航者ZYNQ底板原理图_V3.9.pdf")

# XDC 里的约束
XDC = {
    "aud_bclk":   "M18",
    "aud_daclrc": "G18",
    "aud_adclrc": "L20",
    "aud_mclk":   "E19",
    "aud_adcdat": "M17",
    "aud_dacdat": "G17",
}
PINS = set(XDC.values())

print("=" * 84)
print("核对音频引脚：XDC vs V3.9 原理图")
print("=" * 84)
print("  XDC 声明:")
for k, v in XDC.items():
    print("    %-12s = %s" % (k, v))
print()

if not os.path.exists(PDF):
    print("  ✗ 原理图找不到:", PDF)
    raise SystemExit(1)

doc = fitz.open(PDF)
print("  原理图: %d 页" % doc.page_count)
print()

# 找到含 ES8388 的页
target_pages = []
for i in range(doc.page_count):
    t = doc[i].get_text()
    if "ES8388" in t or "8388" in t:
        target_pages.append(i)
print("  含 ES8388 的页: %s" % [p + 1 for p in target_pages])
print()

for pi in target_pages:
    page = doc[pi]
    words = page.get_text("words")     # (x0,y0,x1,y1,word,block,line,word_no)
    print("=" * 84)
    print("第 %d 页：找 XDC 的引脚号" % (pi + 1))
    print("=" * 84)
    hits = []
    for w in words:
        txt = w[4].strip()
        # 引脚号可能带前缀/后缀
        for name, pin in XDC.items():
            if txt == pin or txt.startswith(pin) and len(txt) <= len(pin) + 2:
                hits.append((w[0], w[1], txt, name, pin))
    if not hits:
        print("  这一页没直接找到这些引脚号")
    else:
        for x, y, txt, name, pin in sorted(hits, key=lambda h: h[1]):
            # 找同一行附近的文字（看它挂在哪个网络名下）
            near = [ww[4] for ww in words
                    if abs(ww[1] - y) < 6 and abs(ww[0] - x) < 220]
            print("  引脚 %-5s (XDC 说是 %-11s)  附近文字: %s"
                  % (txt, name, " ".join(near)[:110]))
    print()

# 再找 ES8388 周围的网络名
print("=" * 84)
print("ES8388 附近的音频网络名")
print("=" * 84)
for pi in target_pages:
    page = doc[pi]
    words = page.get_text("words")
    for w in words:
        t = w[4].strip()
        if re.search(r"(?i)AUD_|BCLK|LRCK|MCLK|SDATA|I2S", t):
            near = [ww[4] for ww in words
                    if abs(ww[1] - w[1]) < 6 and abs(ww[0] - w[0]) < 200]
            print("  第%d页  %-14s  附近: %s"
                  % (pi + 1, t[:14], " ".join(near)[:100]))

doc.close()
print()
print("★ 要看的：ES8388 的 BCLK/LRCK 引脚连的网络名，是不是和 XDC 里")
print("  aud_bclk / aud_daclrc / aud_adclrc 那几个引脚号一一对上。")
