#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kerneldeep.py —— 解开 zImage, 查关键驱动/配置

决定性问题: 他的内核里有没有 aic8800 WiFi 驱动?
  有 -> 换成他的系统后 WiFi 还能起来, 试错可以远程回退
  没有 -> 一旦换过去又启动不了, 就只能等人工插卡恢复
"""
import gzip
import io
import re
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

P = r"D:\总文件夹\FPGA2026\_ref_boot\fit\kernel-1.bin"
b = open(P, "rb").read()
i = b.find(b"\x1f\x8b\x08")
print("gzip 段 @0x%X" % i)
d = zlib.decompressobj(16 + zlib.MAX_WBITS)
img = d.decompress(b[i:], 80 << 20)
print("解出 %d 字节\n" % len(img))

KEYS = [
    (b"aic8800", "aic8800 WiFi 驱动"),
    (b"AIC8800", "AIC8800"),
    (b"aicwf", "aicwf (AIC WiFi 框架)"),
    (b"aic_load_fw", "aic_load_fw"),
    (b"aic8800_fdrv", "aic8800_fdrv 模块名"),
    (b"Linux version", "内核版本串"),
    (b"xlnx_snd_card", "Xilinx 声卡"),
    (b"wm8960", "WM8960 codec"),
    (b"xlnx-v-tc", "v_tc"),
    (b"atk_lcd", "atk 屏驱动"),
    (b"pl-disp", "pl-disp DRM"),
    (b"ov5640", "OV5640 摄像头"),
    (b"xadc", "XADC"),
    (b"CONFIG_IKCONFIG", "内嵌内核配置标记"),
]
print("=" * 74)
print(" 关键字扫描")
print("=" * 74)
for k, desc in KEYS:
    n = img.count(k)
    print("  %-28s %-22s 出现 %d 次" % (k.decode(), desc, n))

print()
print("=" * 74)
print(" 内核版本 / 编译信息")
print("=" * 74)
for m in list(re.finditer(rb"Linux version [\x20-\x7e]{10,160}", img))[:3]:
    print("  " + m.group().decode())

# ---- 内嵌内核配置 (CONFIG_IKCONFIG) ----
# 标记是 "IKCFG_ST" ... "IKCFG_ED", 中间是 gzip 的配置
print()
print("=" * 74)
print(" 内嵌内核配置 (/proc/config.gz 用的那份)")
print("=" * 74)
s = img.find(b"IKCFG_ST")
e = img.find(b"IKCFG_ED")
print("  IKCFG_ST @%s  IKCFG_ED @%s" % (hex(s) if s >= 0 else "无",
                                       hex(e) if e >= 0 else "无"))
if s >= 0 and e > s:
    blob = img[s + 8:e]
    try:
        cfg = gzip.decompress(blob).decode("utf-8", "replace")
        open(r"D:\ubuntu_iso\their_kernel_config.txt", "w",
             encoding="utf-8").write(cfg)
        print("  解出配置 %d 字节 -> their_kernel_config.txt" % len(cfg))
        want = ("CONFIG_MODVERSIONS", "CONFIG_MODULES", "CONFIG_AIC8800",
                "CONFIG_AIC", "CONFIG_CFG80211", "CONFIG_MAC80211",
                "CONFIG_USB_NET", "CONFIG_SDIO", "CONFIG_XILINX_DMA",
                "CONFIG_DRM", "CONFIG_FB", "CONFIG_SOUND", "CONFIG_SND",
                "CONFIG_VIDEO", "CONFIG_LOCALVERSION", "CONFIG_DEBUG_INFO")
        print()
        for line in cfg.splitlines():
            for w in want:
                if line.startswith(w + "=") or line.startswith("# " + w + " "):
                    print("    %s" % line.strip())
                    break
    except Exception as ex:
        print("  解压配置失败: %s" % ex)
