#!/usr/bin/env bash
echo "=== 1) 当前启动用的 bitstream 哈希 ==="
sha256sum /mnt/boot/system.bit 2>/dev/null
echo "  已知：原版 = 8b19413f6c93f002341601074403843ceabd7ad726b017ffbea70bc55e2f5e76"
echo "        实验版 = 1029e7682646213cd68330e7ad9e4e7e6b33985becf2816ffaf05b9aa65826dd"
echo
echo "=== 2) 板上还有哪些 bitstream 备份 ==="
ls -l /mnt/boot/*.bit* 2>/dev/null | awk '{print "  "$5"  "$6" "$7" "$8"  "$9}'
echo
echo "=== 3) 内核启动时的 FPGA 加载信息 ==="
dmesg 2>/dev/null | grep -iE "fpga|bitstream|devcfg|xilinx.*pl|program" | tail -10
echo
echo "=== 4) PL 现在到底配没配（读 formatter 看有没有反应）==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from audio_pl import Mem, FMT_BASE
m=Mem()
try:
    cfg = m.rd(FMT_BASE, 0x000)
    print('  CORE_CONFIG = 0x%08X  -> PL 已配置（寄存器可读）' % cfg)
except Exception as e:
    print('  读失败:', e)
m.close()
" 2>&1 | tail -2
echo
echo "=== 5) 声卡驱动状态 ==="
cat /proc/asound/cards 2>/dev/null | head -3
echo
echo "=== 6) 最近内核有没有音频相关报错 ==="
dmesg 2>/dev/null | grep -iE "es8388|i2s|audio|formatter|dma" | tail -12
