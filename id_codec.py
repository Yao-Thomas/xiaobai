#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id_codec.py —— 读 0x10 的寄存器对比 ES8388/WM8960 默认值 + 查原理图确认板子版本"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import board
import broot

IP = "192.168.10.18"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点原子领航者(V2)ZYNQ开发板资料盘(A盘)"

CMD = r'''
echo "### 读 i2c-1 上 0x10 的寄存器 (ES8388 前 9 个寄存器)"
for r in 00 01 02 03 04 05 06 07 08 17 18 19 1a 1b 1c; do
  printf "  reg 0x%s = " $r
  i2cget -y 1 0x10 0x$r 2>&1 | head -1
done
echo
echo "### 对比: WM8960 在 0x1a"
i2cget -y 1 0x1a 0x00 2>&1 | head -1
echo
echo "### i2c-1 上所有响应/占用的地址"
i2cdetect -y -r 1 2>&1 | tail -10
'''


def pdftext(p, kws):
    """用 pypdf 抽文字 (有就抽, 没有就算了)"""
    try:
        import pypdf
        r = pypdf.PdfReader(p)
        txt = ""
        for pg in r.pages[:12]:
            txt += (pg.extract_text() or "")
        hits = {}
        for k in kws:
            hits[k] = len(re.findall(re.escape(k), txt, re.I))
        return hits, len(txt)
    except Exception as e:
        return {"_err": str(e)}, 0


def main():
    board.HOST = IP
    broot.srun(CMD, timeout=300)

    print("=" * 70)
    print("### 原理图里到底写的是哪个音频芯片")
    kws = ["ES8388", "WM8960", "ES8328", "音频"]
    for sub in ("3_开发板原理图和硬件相关文件",
                r"9_领航者ZYNQ底板V3.7版本（音频芯片为WM8960）\3_开发板原理图"):
        d = os.path.join(BASE, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pdf"):
                hits, n = pdftext(os.path.join(d, f), kws)
                print("  [%s] %s  (抽出 %d 字)" % (sub[:20], f, n))
                print("      %s" % hits)

    print()
    print("### 厂家 es8388.c 里的 I2C 地址 / 驱动名")
    rar = os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "Linux驱动例程.rar")
    for name in ("es8388.c",):
        r = subprocess.run([r"C:\Program Files\WinRAR\UnRAR.exe", "p", "-inul", rar,
                            "Linux驱动例程\\28_codec\\" + name],
                           capture_output=True, timeout=600)
        t = r.stdout.decode("gbk", "replace")
        print("  --- %s (%d 字节) ---" % (name, len(t)))
        for ln in t.splitlines():
            if re.search(r"addr|ADDR|0x1[0-9a-f]|i2c_driver|\.name|compatible|of_device_id",
                         ln):
                print("     " + ln.strip()[:110])


main()
