#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把底板原理图的音频那页渲染成 PNG，好看清耳机座/喇叭接到哪"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PDF = (r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
       r"\3_开发板原理图和硬件相关文件\领航者ZYNQ底板原理图_V3.9.pdf")
OUT = r"D:\ubuntu_iso"

try:
    import fitz                      # PyMuPDF
    print("pymupdf:", fitz.__doc__)
except Exception as e:
    print("没有 pymupdf:", e)
    print("试 pypdfium2 ...")
    try:
        import pypdfium2 as pdfium
    except Exception as e2:
        sys.exit("都不行: %s" % e2)
    pdf = pdfium.PdfDocument(PDF)
    n = len(pdf)
    print("页数", n)
    for i in range(n):
        pg = pdf[i]
        img = pg.render(scale=3.0).to_pil()
        p = os.path.join(OUT, "_sch_p%d.png" % (i + 1))
        img.save(p)
        print("  第 %d 页 -> %s  %s" % (i + 1, p, img.size))
    sys.exit(0)

doc = fitz.open(PDF)
print("页数", doc.page_count)
for i in range(doc.page_count):
    pg = doc[i]
    m = fitz.Matrix(3.0, 3.0)
    pix = pg.get_pixmap(matrix=m)
    p = os.path.join(OUT, "_sch_p%d.png" % (i + 1))
    pix.save(p)
    print("  第 %d 页 -> %s  %dx%d" % (i + 1, p, pix.width, pix.height))

    # 顺便把这一页里含关键词的文字块位置打出来，方便裁剪
    if i == 1:
        words = pg.get_text("words")
        KEYS = ("PHONE", "SPK", "ES8388", "LOUT", "ROUT", "MIC", "LINE")
        print("  --- 关键词位置 (x0,y0,x1,y1 文字) ---")
        for w in words:
            if any(k in w[4].upper() for k in KEYS):
                print("     %6.1f %6.1f %6.1f %6.1f  %s"
                      % (w[0], w[1], w[2], w[3], w[4]))
