#!/bin/sh
# cleanup_boot.sh —— 清理 /mnt/boot 里的旧 bitstream 备份
# 用法: sudo sh cleanup_boot.sh          # 演练
#       sudo sh cleanup_boot.sh --apply  # 真删
#
# ★ 安全设计：用【显式白名单 + 显式删除清单】，绝不使用通配符 rm。
#   白名单外的文件一个都不动，system.bit 永远保留。

BOOT=/mnt/boot
APPLY=0
[ "$1" = "--apply" ] && APPLY=1

# 必须保留（当前启动 + 已知可用 + 管家小白依赖的音频修复版 + 出厂）
KEEP="system.bit system.bit.bak_before_j4 system.bit.bak_audio_clockfix_20260928 system.bit.origbak"

# 明确要删的（都是被后续版本超越的中间产物）
DEL="system.bit.bak_1010_1833
system.bit.bak_20261009_192443
system.bit.bak_20261009_192452
system.bit.bak_20261009_192500
system.bit.bak_agent_20261003_173246
system.bit.bak_agent_20261003_233325
system.bit.bak_before_addraddr_20261001_173322
system.bit.bak_before_cnn_20261001_165213
system.bit.bak_before_dual
system.bit.bak_before_gpu
system.bit.bak_before_rxbclk
system.bit.bak_before_scp3
system.bit.bak_v3_1010_1829
system.bit.binbak"

echo "=== 保留 ==="
for f in $KEEP; do
    if [ -f "$BOOT/$f" ]; then
        echo "  KEEP  $f  ($(stat -c%s "$BOOT/$f") 字节)"
    fi
done

echo
echo "=== 计划删除 ==="
TOTAL=0
for f in $DEL; do
    if [ -f "$BOOT/$f" ]; then
        SZ=$(stat -c%s "$BOOT/$f")
        TOTAL=$((TOTAL + SZ))
        if [ "$APPLY" = "1" ]; then
            rm -f "$BOOT/$f" && echo "  DEL   $f  ($SZ 字节)"
        else
            echo "  (演练) $f  ($SZ 字节)"
        fi
    fi
done
echo "  合计约 $((TOTAL / 1024 / 1024)) MB"

echo
if [ "$APPLY" = "1" ]; then
    sync
    echo "=== 删除后 ==="
else
    echo "=== 当前（演练，未删除）==="
fi
ls -1 "$BOOT"/system.bit* 2>/dev/null | sed "s|$BOOT/||" | while read x; do echo "  $x"; done
echo
df -h "$BOOT" | tail -1
echo "CLEANUP_DONE"
