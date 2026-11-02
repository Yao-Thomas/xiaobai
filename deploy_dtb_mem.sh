#!/bin/sh
# deploy_dtb_mem.sh —— 部署带 mem=992M 的设备树
#
# ★ 备份策略：原来的 system.dtb 会存成 system.dtb.bak_mem992
#   万一板子起不来，把 SD 卡插到电脑上，把
#       system.dtb.bak_mem992  改名回  system.dtb
#   就能恢复。
#
# 改动只有 8 个字节（bootargs 里 earlycon -> mem=992M，等长替换），
# 结构已用 DTB 解析器验证过（161 节点/965 属性/结尾 depth=0，与原版一致）。

set -e
MNT=/mnt/boot
SRC=/home/zynq/system.dtb.new
WANT_MD5=ece3cd8d656c7b26cd39ee8c8585d001

echo "======================================================"
echo " 部署设备树（加 mem=992M，预留 32MB 给 PL）"
echo "======================================================"
echo

echo "① 校验待部署文件"
GOT=$(md5sum $SRC | cut -d' ' -f1)
echo "   期望 $WANT_MD5"
echo "   实得 $GOT"
if [ "$GOT" != "$WANT_MD5" ]; then
    echo "   ★ md5 不符，中止"
    exit 1
fi
SIZE=$(stat -c %s $SRC)
echo "   大小 $SIZE 字节"
if [ "$SIZE" != "29180" ]; then
    echo "   ★ 大小不对（应该是 29180），中止"
    exit 1
fi
echo "   ✓ 通过"
echo

echo "② 挂启动分区"
mountpoint -q $MNT || mount /dev/mmcblk0p1 $MNT
ls -l $MNT/system.dtb | sed 's/^/   /'
echo -n "   当前 md5: "; md5sum $MNT/system.dtb | cut -d' ' -f1
echo

echo "③ 备份原 DTB"
BAK=$MNT/system.dtb.bak_mem992
cp -f $MNT/system.dtb $BAK
sync
echo "   ✓ $BAK  ($(stat -c %s $BAK) 字节)"
echo "     md5 $(md5sum $BAK | cut -d' ' -f1)"
echo "   ★ 万一开不了机：把 SD 卡插电脑，"
echo "      system.dtb.bak_mem992 改名回 system.dtb 即可恢复"
echo

echo "④ 原子写入新 DTB"
cp -f $SRC $MNT/system.dtb.new
sync
G2=$(md5sum $MNT/system.dtb.new | cut -d' ' -f1)
if [ "$G2" != "$WANT_MD5" ]; then
    echo "   ★ SD 上校验失败，不动 system.dtb"
    rm -f $MNT/system.dtb.new
    exit 1
fi
mv -f $MNT/system.dtb.new $MNT/system.dtb
sync
echo "   ✓ 已替换"
ls -l $MNT/system.dtb | sed 's/^/   /'
echo -n "   新 md5: "; md5sum $MNT/system.dtb | cut -d' ' -f1
echo

echo "⑤ 确认 bootargs 里有 mem="
strings $MNT/system.dtb 2>/dev/null | grep -o "rootwait[^\x00]*" | head -2 | sed 's/^/   /' || true
echo

echo "⑥ 备份也留一份到 /home/zynq（方便 PC 侧取救）"
cp -f $BAK /home/zynq/system.dtb.bak_mem992 2>/dev/null || true
ls -l /home/zynq/system.dtb.bak_mem992 2>/dev/null | sed 's/^/   /'
echo

echo "⑦ 卸载"
sync
umount $MNT 2>/dev/null || true
echo

echo "======================================================"
echo " 部署完成。重启后生效："
echo "   · /proc/cmdline 里应该出现 mem=992M"
echo "   · /proc/iomem 里 System RAM 上界应该变成 0x3EFFFFFF"
echo "   · 0x3E000000~0x3FFFFFFF（32MB）空出来给 PL 用"
echo "======================================================"
