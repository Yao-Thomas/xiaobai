set -e
SRC=/home/zynq/cnn_new.bit
WANT=6061f2c84b5544bc37ab79496c47a77c

echo "--- 校验上传的文件 ---"
GOT=\
echo "  want=\"
echo "  got =\"
if [ "\" != "\" ]; then echo "!! md5 不符，中止"; exit 1; fi

mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
if [ ! -f /mnt/boot/BOOT.BIN ]; then echo "!! 不是启动分区，中止"; umount /mnt/boot; exit 1; fi

echo "--- 备份当前 bitstream ---"
TS=\
cp /mnt/boot/system.bit /mnt/boot/system.bit.bak_before_cnn_\
echo "  备份: system.bit.bak_before_cnn_\"
ls -la /mnt/boot/system.bit.bak_before_cnn_\

echo "--- 原子写入 ---"
cp \ /mnt/boot/system.bit.new
sync
NEW=\
echo "  .new 的 md5 = \"
if [ "\" != "\" ]; then echo "!! .new 校验失败，中止（原文件未动）"; rm -f /mnt/boot/system.bit.new; exit 1; fi
mv /mnt/boot/system.bit.new /mnt/boot/system.bit
sync

echo "--- 装好了 ---"
md5sum /mnt/boot/system.bit
ls -la /mnt/boot/system.bit
umount /mnt/boot 2>/dev/null || true
echo "RESULT=OK"