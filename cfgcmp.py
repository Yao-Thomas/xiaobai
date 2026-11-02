#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cfgcmp.py —— 三方内核 config 对比

  A = SD 启动分区自带的 board_config.gz   (厂家原始 .config)
  B = image.ub 里他的 kernel-1.bin        (他实际编译用的 config)
  C = 我们板上跑的 zImage                  (我们实际编译用的 config)

先解外层 gzip 得到裸内核, 再找内核内嵌的 IKCFG_ST..IKCFG_ED (gzip) 解开。
"""
import gzip
import hashlib
import io
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATHS = {
    "A_SD的board_config": (r"D:\ubuntu_iso\board_config.raw", None),
    "B_image.ub他的kernel": (r"D:\总文件夹\FPGA2026\_ref_boot\fit\kernel-1.bin", "gz"),
    "C_我们的zImage": (r"D:\总文件夹\FPGA2026\_boot_backup_0926_192947\zImage", "gz"),
}


def gunzip_at(d, off):
    """从 off 开始做 gzip 解压, 返回全部输出"""
    o = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = o.decompress(d[off:])
    out += o.flush()
    return out


def embedded_config(path, outer):
    d = open(path, "rb").read()
    if outer == "gz":
        m = d.find(b"\x1f\x8b\x08")
        if m < 0:
            return None, "找不到 gzip"
        d = gunzip_at(d, m)
    a = d.find(b"IKCFG_ST")
    b = d.find(b"IKCFG_ED")
    if a < 0 or b < 0:
        return None, "裸内核里没找到 IKCFG_ST (len=%d)" % len(d)
    return gzip.decompress(d[a + 8:b]), "裸内核 %d 字节, cfg @%d..%d" % (len(d), a, b)


cfgs = {}
for name, (p, outer) in PATHS.items():
    try:
        c, note = embedded_config(p, outer)
    except Exception as e:
        c, note = None, "异常 %s" % e
    print("%-22s %s" % (name, note))
    if c:
        print("%-22s config %d 字节 md5=%s" % ("", len(c), hashlib.md5(c).hexdigest()))
        cfgs[name] = c
        open(r"D:\ubuntu_iso\cfg_%s.txt" % name[0], "w", encoding="utf8").write(
            c.decode("utf8", "replace"))

print()
names = list(cfgs)
base = cfgs[names[0]]


def norm(b):
    s = set()
    for l in b.decode("utf8", "replace").splitlines():
        l = l.strip()
        if l and not l.startswith("#"):
            s.add(l)
    return s


for n in names[1:]:
    sb, sn = norm(base), norm(cfgs[n])
    same = sb & sn
    only_b = sb - sn
    only_n = sn - sb
    print("=== %s vs %s" % (n, names[0]))
    print("    相同 %d 行 | 仅前者有 %d | 仅后者有 %d" % (len(same), len(only_b), len(only_n)))
    for x in sorted(only_b):
        print("      [%s独有] %s" % (names[0][0], x))
    for x in sorted(only_n):
        print("      [%s独有] %s" % (n[0], x))

# 关键项
KEYS = ["CONFIG_MODVERSIONS", "CONFIG_MODULE_FORCE_LOAD", "CONFIG_MODULE_SIG",
        "CONFIG_MODULE_SIG_FORCE", "CONFIG_CFG80211", "CONFIG_MAC80211",
        "CONFIG_LOCALVERSION", "CONFIG_LOCALVERSION_AUTO", "CONFIG_USB",
        "CONFIG_USB_NET_DRIVERS", "CONFIG_DRM", "CONFIG_FB", "CONFIG_SND",
        "CONFIG_XILINX_DMA", "CONFIG_CMA", "CONFIG_EXT4_FS", "CONFIG_DEVTMPFS",
        "CONFIG_USB_STORAGE", "CONFIG_MMC", "CONFIG_MMC_SDHCI", "CONFIG_MTD",
        "CONFIG_SMP", "CONFIG_PREEMPT", "CONFIG_ARM_LPAE", "CONFIG_HIGHMEM"]
print()
print("=== 关键配置项 ===")
print("%-28s %-32s %-32s %-32s" % ("KEY", *[n[:30] for n in names]))
for k in KEYS:
    row = []
    for n in names:
        v = [l for l in norm(cfgs[n]) if l.startswith(k + "=")]
        row.append(v[0] if v else ("# " + k + " is not set"
                                   if ("# " + k + " is not set") in
                                   cfgs[n].decode("utf8", "replace") else "(缺)"))
    print("%-28s %-32s %-32s %-32s" % (k, *row))
