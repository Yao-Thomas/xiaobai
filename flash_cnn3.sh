#!/bin/sh
# flash_cnn3.sh —— 原子刷写（带 md5 校验 + 备份）
set -e

SRC=/home/zynq/cnn_new.bit
WANT=d4574dce0b8506251aca7afbbdc45e7d
DST=/mnt/boot/system.bit

echo "--- 1) 校验上传的文件 ---"
GOT=$(md5sum "$SRC" | cut -d' ' -f1)
echo "  want = $WANT"
echo "  got  = $GOT"
if [ "$GOT" != "$WANT" ]; then
    echo "!! md5 不符，中止"
    exit 1
fi
echo "  OK"

echo
echo "--- 2) 挂载启动分区 ---"
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
[ -f /mnt/boot/BOOT.BIN ] || { echo "!! 不是启动分区"; umount /mnt/boot 2>/dev/null||true; exit 1; }
echo "  OK"

echo
echo "--- 3) 备份当前 ---"
TS=$(date +%Y%m%d_%H%M%S)
BAK="/mnt/boot/system.bit.bak_before_addraddr_$TS"
cp "$DST" "$BAK"
echo "  -> $BAK"

echo
echo "--- 4) 原子写入 ---"
cp "$SRC" /mnt/boot/system.bit.new
sync
NEW=$(md5sum /mnt/boot/system.bit.new | cut -d' ' -f1)
if [ "$NEW" != "$WANT" ]; then
    echo "!! .new 校验失败，原文件未动"
    rm -f /mnt/boot/system.bit.new
    exit 1
fi
mv /mnt/boot/system.bit.new "$DST"
sync

echo
echo "--- 5) 装好了 ---"
md5sum "$DST"
umount /mnt/boot 2>/dev/null || true
echo "RESULT=OK"
