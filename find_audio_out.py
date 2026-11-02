#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_audio_out.py —— 从 V3.9 底板原理图里找音频输出接口（耳机座/喇叭座）"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"
PDF = os.path.join(BASE, "3_开发板原理图和硬件相关文件", "领航者ZYNQ底板原理图_V3.9.pdf")

KW = re.compile(r"PHONE|HEADPHONE|SPK|SPEAKER|EARPHONE|耳机|喇叭|扬声器|HP_|LOUT|ROUT|"
                r"ES8388|MIC|LINEIN|LINE_IN", re.I)


def main():
    print("原理图:", os.path.basename(PDF), os.path.getsize(PDF))
    try:
        import pypdf
    except ImportError:
        print("没装 pypdf，试试 PyPDF2")
        try:
            import PyPDF2 as pypdf
        except ImportError:
            print("都没有，跳过")
            return
    r = pypdf.PdfReader(PDF)
    print("页数", len(r.pages))
    hits = 0
    for pi, pg in enumerate(r.pages):
        t = pg.extract_text() or ""
        for ln in t.splitlines():
            if KW.search(ln):
                s = ln.strip()
                if len(s) > 3:
                    print("  p%-3d %s" % (pi + 1, s[:110]))
                    hits += 1
                    if hits > 60:
                        return


main()
