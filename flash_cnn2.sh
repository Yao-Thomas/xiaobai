#!/bin/sh
# flash_cnn2.sh —— 原子地把 CNN bitstream 写进 SD 的启动分区
#
# 为什么原子：直接 cp 覆盖 /mnt/boot/system.bit，如果传到一半 WiFi 断了，
# 那个文件就是半截的 -> 下次 u-boot 加载 PL 失败。所以：
#   先写 system.bit.new -> 校验 md5 -> 再 mv 改名（mv 是原子操作）
set -e

SRC=/home/zynq/cnn_new.bit
WANT=6061f2c84b5544bc37ab79496c47a77c
DST=/mnt/boot/system.bit

echo "--- 1) 校验上传的文件 ---"
GOT=$(md5sum "$SRC" | cut -d' ' -f1)
echo "  want = $WANT"
echo "  got  = $GOT"
if [ "$GOT" != "$WANT" ]; then
    echo "!! md5 不符，中止（没动启动分区）"
    exit 1
fi
echo "  OK 上传文件完整"

echo
echo "--- 2) 挂载启动分区 ---"
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
if [ ! -f /mnt/boot/BOOT.BIN ]; then
    echo "!! /mnt/boot 里没有 BOOT.BIN，不像启动分区，中止"
    umount /mnt/boot 2>/dev/null || true
    exit 1
fi
echo "  OK 启动分区已挂载"

echo
echo "--- 3) 备份当前 bitstream ---"
TS=$(date +%Y%m%d_%H%M%S)
BAK="/mnt/boot/system.bit.bak_before_cnn_$TS"
cp "$DST" "$BAK"
echo "  备份 -> $BAK"
ls -la "$BAK"

echo
echo "--- 4) 原子写入 ---"
cp "$SRC" /mnt/boot/system.bit.new
sync
NEW=$(md5sum /mnt/boot/system.bit.new | cut -d' ' -f1)
echo "  .new 的 md5 = $NEW"
if [ "$NEW" != "$WANT" ]; then
    echo "!! .new 校验失败，中止（原文件未动）"
    rm -f /mnt/boot/system.bit.new
    exit 1
fi
mv /mnt/boot/system.bit.new "$DST"
sync

echo
echo "--- 5) 装好了 ---"
md5sum "$DST"
ls -la "$DST"
umount /mnt/boot 2>/dev/null || true

echo
echo "=== 现有备份清单 ==="
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -la /mnt/boot/system.bit* 2>/dev/null
umount /mnt/boot 2>/dev/null || true
echo
echo "RESULT=OK"
