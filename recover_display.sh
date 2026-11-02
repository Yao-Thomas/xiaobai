#!/bin/bash
#=====================================================================
#  recover_display.sh —— 恢复显示 (重启前先把状态弄干净)
#=====================================================================
set -u
echo "=== [1] 解除桌面的 mask (我测试时 mask 掉了) ==="
systemctl unmask zynq-desktop 2>&1 | tail -1
systemctl enable zynq-desktop 2>&1 | tail -1

echo ""
echo "=== [2] 清掉所有 GPU 标记 (防止重启后桌面 SIGBUS) ==="
rm -f /home/zynq/.gpu_addr /home/zynq/.gpu_addr.disabled
echo "  已清理"

echo ""
echo "=== [3] 确认 .fb_phys 还在 (桌面需要它跑快路径) ==="
if [ -f /home/zynq/.fb_phys ]; then
    echo "  ✅ 存在: $(cat /home/zynq/.fb_phys)"
else
    echo "  ❌ 不存在"
fi

echo ""
echo "=== [4] 确认 GPU 加载器还是禁用的 ==="
echo -n "  zynq-gpu-loader: "; systemctl is-enabled zynq-gpu-loader 2>&1

echo ""
echo "=== [5] 确认 SD 卡上 u-boot 会不会烧我们的 bitstream ==="
if [ -b /dev/mmcblk0p1 ]; then
    mkdir -p /mnt/bootp
    mount /dev/mmcblk0p1 /mnt/bootp 2>/dev/null && {
        if [ -f /mnt/bootp/system.bit ]; then
            echo "  ⚠️ 卡上有 system.bit — u-boot 会尝试加载它"
            echo "     (实测 fpga loadb 失败, 所以 PL 仍是原厂设计, 显示正常)"
        else
            echo "  ✅ 卡上没有 system.bit"
        fi
        umount /mnt/bootp
    }
fi

echo ""
echo "=== [6] 最后状态 ==="
echo -n "  桌面服务: "; systemctl is-enabled zynq-desktop 2>&1
echo -n "  GPU 标记: "; ls /home/zynq/.gpu_addr 2>/dev/null || echo "无 ✅"
echo -n "  网络: "; hostname -I | awk '{print $1}'
echo ""
echo "  ★ 现在可以安全重启了: sudo reboot"
echo DONE-RECOVER
