#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从底板原理图 PDF 里找音频相关的东西（耳机座/喇叭/ES8388 引脚）"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\3_开发板原理图和硬件相关文件\领航者ZYNQ底板原理图_V3.9.pdf")

print("PDF:", os.path.basename(PDF), os.path.getsize(PDF), "字节")

text = None
for mod in ("pypdf", "PyPDF2", "pdfminer.high_level", "fitz"):
    try:
        if mod == "pdfminer.high_level":
            from pdfminer.high_level import extract_text
            text = extract_text(PDF)
        elif mod == "fitz":
            import fitz
            d = fitz.open(PDF)
            text = "\n\f\n".join(p.get_text() for p in d)
        else:
            m = __import__(mod)
            R = getattr(m, "PdfReader")
            r = R(PDF)
            text = "\n\f\n".join((pg.extract_text() or "") for pg in r.pages)
        print("用 %s 解析成功，%d 字符" % (mod, len(text)))
        break
    except Exception as e:
        print("  %s 不行: %s" % (mod, str(e)[:90]))

if not text:
    sys.exit("没有可用的 PDF 库")

pages = text.split("\f")
print("共 %d 页" % len(pages))

KEYS = ["耳机", "PHONE", "PHON", "HP_", "HEAD", "喇叭", "SPEAK", "SPK",
        "LINE", "ES8388", "WM8960", "MIC", "AUDIO", "音频", "LOUT", "ROUT"]

for i, pg in enumerate(pages, 1):
    hit = [k for k in KEYS if k in pg.upper() or k in pg]
    if not hit:
        continue
    print("\n" + "=" * 78)
    print("### 第 %d 页   命中: %s" % (i, " ".join(hit)))
    # 只打含关键词的行
    for ln in pg.splitlines():
        s = ln.strip()
        if any(k in s.upper() or k in s for k in KEYS):
            print("   ", s[:150])
