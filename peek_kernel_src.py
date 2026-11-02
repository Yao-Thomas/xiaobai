#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peek_kernel_src.py —— 从 rar 里取出内核 tarball, 直接读声卡驱动的关键片段"""
import io
import os
import subprocess
import sys
import tarfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
BASE = r"D:\总文件夹\FPGA2026\板卡资料\正点领航者(V2)ZYNQ开发板资料盘(A盘)".replace("正点领航者", "正点原子领航者")
RAR = os.path.join(BASE, "4_Source_Code", "3_Embedded_Linux", "资源文件.rar")
TMP = r"D:\ubuntu_iso\_kernel_atk.tar.gz"

WANT = ("sound/soc/xilinx/xlnx_snd_card.c",
        "sound/soc/xilinx/xlnx_pl_snd_card.c",
        "sound/soc/codecs/es8388.c",
        "sound/soc/codecs/es8328.c",
        "sound/soc/codecs/wm8960.c")


def main():
    if not os.path.exists(TMP):
        print("从 rar 里抽 atk-zynq-linux-xlnx.tar.gz ...")
        r = subprocess.run([UNRAR, "p", "-inul", RAR,
                            r"资源文件\Kernel\atk-zynq-linux-xlnx.tar.gz"],
                           capture_output=True, timeout=3600)
        print("  返回码 %d, 抽出 %d 字节" % (r.returncode, len(r.stdout)))
        if len(r.stdout) < 10000:
            print("  抽出来太小, 失败")
            return
        open(TMP, "wb").write(r.stdout)
    print("tarball %.0f MB" % (os.path.getsize(TMP) / 1e6))

    print()
    print("### 在 tarball 里找音频相关源码")
    names = []
    with tarfile.open(TMP, "r:gz") as tf:
        for i, m in enumerate(tf):
            n = m.name
            if re.search(r"sound/soc/(xilinx|codecs)/(xlnx|es8388|es8328|wm8960)", n, re.I):
                names.append((n, m.size))
            if i > 200000:
                break
    for n, s in names[:40]:
        print("   %9d  %s" % (s, n))

    print()
    print("### 读 xlnx 声卡驱动里关于 dummy codec / audio-codec 的部分")
    target = [n for n, s in names if n.endswith(("xlnx_snd_card.c", "xlnx_pl_snd_card.c"))]
    if not target:
        print("   (没找到)")
        return
    with tarfile.open(TMP, "r:gz") as tf:
        for t in target:
            f = tf.extractfile(t)
            txt = f.read().decode("utf8", "replace")
            print("=" * 74)
            print("### %s  (%d 字节)" % (t, len(txt)))
            print("=" * 74)
            for ln in txt.splitlines():
                if re.search(r"dummy|audio-codec|audio_codec|codec_dai|codec_name|"
                             r"of_parse_phandle|snd_soc_of_get_dai|EPROBE_DEFER|"
                             r"platform_name|cpu_dai|static struct snd_soc_dai_link|"
                             r"\.name\s*=|SND_SOC_DAILINK", ln):
                    print("   " + ln.rstrip()[:120])


import re  # noqa: E402

main()
