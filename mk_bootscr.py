#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mk_bootscr.py —— 生成带"试一次就自动退回"的 boot.scr

原 boot.scr 的致命点:
    if test -e ... /image.ub; then fatload ... image.ub; bootm 0x10000000; exit; fi
无条件 + exit —— SD 上只要有 image.ub, 他的系统起不来 u-boot 就永远停住。
我们没有串口, 那就只能拆 SD 卡。所以必须换掉。

新版逻辑 (mmc 分支):
    use_ours.flag 存在   -> 直接走我们自己的 zImage/system.dtb/system.bit
    不存在               -> 先 fatwrite 一个 use_ours.flag, 再 bootm image.ub
                            bootm 失败(内核 panic 会自动重启) -> 掉下来走我们的路
"只试一次"由 flag 保证; 要再试一次就删掉 SD 上的 use_ours.flag。

镜像头 (image_header_t, 64B, 大端) 原样沿用模板的 os/arch/type/comp 与正文前 8 字节:
    0x00 magic 0x27051956  0x04 hcrc  0x08 time  0x0C size
    0x10 load  0x14 ep      0x18 dcrc  0x1C os  arch  type  comp   0x20 name[32]
正文 = pack(">II", len(text), 0) + text       (模板就是 `00 00 08 4f 00 00 00 00` + 文本)
"""
import binascii
import io
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TEMPLATE = r"D:\总文件夹\FPGA2026_项目交接包\01_板载系统备份\引导文件\boot.scr"
OUT = r"D:\ubuntu_iso\boot_try_his.scr"

SCRIPT = r'''# Generate boot.scr:
# mkimage -c none -A arm -T script -d boot.cmd.default boot.scr
#  --- modified: one-shot trial of HIS image.ub, auto fallback to ours ---
################

for boot_target in ${boot_targets};
do
	if test "${boot_target}" = "jtag" ; then
		bootm 0x00200000 0x04000000 0x00100000
		exit;
	fi
	if test "${boot_target}" = "mmc0" || test "${boot_target}" = "mmc1" ; then
		setenv try_his 1;
		if test -e ${devtype} ${devnum}:${distro_bootpart} /use_ours.flag; then
			setenv try_his 0;
			echo "[boot] use_ours.flag present, use OUR system";
		fi
		if test "${try_his}" = "1"; then
			if test -e ${devtype} ${devnum}:${distro_bootpart} /image.ub; then
				echo "[boot] ONE-SHOT trial of HIS system";
				fatwrite ${devtype} ${devnum}:${distro_bootpart} 0x00100000 use_ours.flag 4;
				setenv bootargs console=ttyPS0,115200 cma=50M earlycon root=/dev/mmcblk0p2 rw rootwait panic=10;
				fatload ${devtype} ${devnum}:${distro_bootpart} 0x10000000 image.ub;
				bootm 0x10000000;
				echo "[boot] HIS bootm returned, falling back";
			fi
		fi
		if test -e ${devtype} ${devnum}:${distro_bootpart} /zImage; then
			fatload ${devtype} ${devnum}:${distro_bootpart} 0x00200000 zImage;
		fi
		if test -e ${devtype} ${devnum}:${distro_bootpart} /system.dtb; then
			fatload ${devtype} ${devnum}:${distro_bootpart} 0x00100000 system.dtb;
		fi
		if test -e ${devtype} ${devnum}:${distro_bootpart} /rootfs.cpio.gz.u-boot; then
			fatload ${devtype} ${devnum}:${distro_bootpart} 0x04000000 rootfs.cpio.gz.u-boot;
			bootm 0x00200000 0x04000000 0x00100000
			exit;
		fi
		if test -e ${devtype} ${devnum}:${distro_bootpart} /system.bit; then
			fatload ${devtype} ${devnum}:${distro_bootpart} 0x00800000 system.bit;
			fpga loadb 0 ${fileaddr} ${filesize}
		fi
		bootz 0x00200000 - 0x00100000
		exit;
	fi
	if test "${boot_target}" = "xspi0" || test "${boot_target}" = "qspi" || test "${boot_target}" = "qspi0"; then
		sf probe 0 0 0;
		if test "image.ub" = "image.ub"; then
			sf read 0x10000000 0x1000000 0xF00000;
			bootm 0x10000000;
			exit;
		fi
		exit;
	fi
	if test "${boot_target}" = "nand" || test "${boot_target}" = "nand0"; then
		nand info
		if test "image.ub" = "image.ub"; then
			nand read 0x10000000 0x1000000 0x6400000;
			bootm 0x10000000;
			exit;
		fi
	fi
done
'''


def main():
    tpl = open(TEMPLATE, "rb").read()
    magic, hcrc, t0, sz, load, ep, dcrc = struct.unpack(">7I", tpl[:28])
    os_, arch, typ, comp = tpl[28], tpl[29], tpl[30], tpl[31]
    name = tpl[32:64]

    if magic != 0x27051956:
        raise SystemExit("not a u-boot image")
    if not tpl[64:].startswith(struct.pack(">II", sz - 8, 0)):
        raise SystemExit("模板正文前缀不是 len+0, 别乱套")

    print("模板: size=%d os=%d arch=%d type=%d comp=%d" % (sz, os_, arch, typ, comp))

    text = SCRIPT.encode("ascii")
    data = struct.pack(">II", len(text), 0) + text
    print("正文: 8 + %d = %d 字节 (模板 %d)" % (len(text), len(data), sz))

    def build(hcrc_v, dcrc_v):
        return struct.pack(">7I4B", magic, hcrc_v, t0, len(data), load, ep,
                           dcrc_v, os_, arch, typ, comp) + name

    dc = binascii.crc32(data) & 0xFFFFFFFF
    hc = binascii.crc32(build(0, dc)) & 0xFFFFFFFF
    out = build(hc, dc) + data

    # 自检: 用同一套规则把模板读回来, 确认 CRC 算法对得上
    assert binascii.crc32(tpl[64:]) & 0xFFFFFFFF == dcrc, "数据 CRC 算法与模板不符"
    tpl_hdr_zeroed = tpl[:4] + b"\x00\x00\x00\x00" + tpl[8:64]
    assert binascii.crc32(tpl_hdr_zeroed) & 0xFFFFFFFF == hcrc, "头 CRC 算法与模板不符"

    open(OUT, "wb").write(out)
    print("写出 %s (%d 字节) hcrc=%08X dcrc=%08X" % (OUT, len(out), hc, dc))

    # 再做一次独立校验
    r = open(OUT, "rb").read()
    assert binascii.crc32(r[64:]) & 0xFFFFFFFF == struct.unpack(">I", r[24:28])[0]
    print("自检 OK")


main()
