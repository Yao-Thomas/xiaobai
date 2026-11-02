#!/bin/bash
#=====================================================================
#  verify_gpu_boot.sh —— 验证 u-boot 加载的 GPU 是否真的在 PL 里
#=====================================================================
set -u
echo "=== [1] 桌面状态 (确认显示正常) ==="
systemctl is-active zynq-desktop
tail -4 /var/log/zynq-desktop.log | sed 's/^/    /'

echo ""
echo "=== [2] ★ 探测 GPU (在子进程里做, 即使 SIGBUS 也不影响) ==="
python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
try:
    from gpu import GPU
    g = GPU(0x43CB0000, verbose=False)
    ok = g.probe()
    print('  0x43CB0000:', '存在 ✅ GPU 已在 PL 里!' if ok else '存在但无响应')
    if ok:
        for n,o in (('CTRL',0),('OP',4),('BASE',8),('STRIDE',0xC),('COLOR',0x18),('PIXCNT',0x1C),('STATUS',0x20)):
            print('    %-8s = 0x%08X' % (n, g.rd(o)))
    g.close()
    sys.exit(0 if ok else 1)
except Exception as e:
    print('  0x43CB0000: 不存在 (SIGBUS) -> PL 里还是原始设计')
    sys.exit(1)
" 2>/dev/null
GPU_OK=$?

echo ""
echo "=== [3] 判断 ==="
if [ $GPU_OK -eq 0 ]; then
    echo "  ✅✅ GPU 在 PL 里! u-boot 的 fpga loadb 成功了!"
    echo "  下一步: 写 .gpu_addr 让桌面启用硬件加速"
else
    echo "  ⚠️ GPU 不在 —— 可能 fpga loadb 的格式/地址不对"
    echo "  但显示正常, 系统完全可用, 无风险"
fi

echo ""
echo "=== [4] framebuffer 物理地址 (GPU 需要) ==="
cat /home/zynq/.fb_phys 2>/dev/null || echo "  (.fb_phys 不存在, 需要重新测量)"

echo ""
echo "=== [5] 显存信息 ==="
cat /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null
echo DONE
