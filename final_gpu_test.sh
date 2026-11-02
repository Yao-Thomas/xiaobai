#!/bin/bash
#=====================================================================
#  final_gpu_test.sh —— 加载新 bitstream 并用 GPU 画图验证
#=====================================================================
set -u

echo "=== [1] 加载新 bitstream ==="
cp -f /home/zynq/gpu_system_swapped.bit.bin /lib/firmware/gpu.bin
echo gpu.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 3
echo -n "  FPGA Manager 状态: "; cat /sys/class/fpga_manager/fpga0/state

echo ""
echo "=== [2] 停掉桌面 (mask 防止重启) ==="
systemctl stop zynq-desktop 2>/dev/null
systemctl mask zynq-desktop >/dev/null 2>&1
sleep 2
echo -n "  桌面: "; systemctl is-active zynq-desktop

echo ""
echo "=== [3] GPU 探测 ==="
cd /home/zynq/ui
python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
from gpu import GPU
g = GPU(0x43CB0000, verbose=False)
print('  GPU:', '存在 ✅' if g.probe() else '无响应 ❌')
g.close()
"

echo ""
echo "=== [4] 清屏 (CPU 写深灰, 作为对照) ==="
python3 -c "
import mmap, os
fd = os.open('/dev/fb0', os.O_RDWR)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ|mmap.PROT_WRITE)
mm[:] = b'\x10\x10\x10' * (1024*600)
mm.flush(); mm.close(); os.close(fd)
print('  已清成深灰 #101010')
"

echo ""
echo "=== [5] ★ 用 FPGA GPU 画图 ==="
python3 gpu_show.py 2>&1 | sed 's/^/  /'

echo ""
echo "=== [6] ★★ 读回屏幕像素 (验证数据真的写进去了) ==="
python3 -c "
import mmap, os
fd = os.open('/dev/fb0', os.O_RDONLY)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ)
pts = ((100,150,'红块内应为#E03030'),(400,150,'绿块内应为#30C060'),
       (700,150,'蓝块内应为#3070E0'),(25,22,'顶部黄条应为#F0D030'),
       (512,455,'区域(应深蓝#101A30)'))
ok = 0
for (x,y,name) in pts:
    o = y*3072 + x*3
    b,g,r = mm[o], mm[o+1], mm[o+2]
    print('  %-26s = #%02X%02X%02X' % (name, r, g, b))
mm.close(); os.close(fd)
"
echo "DONE-FINAL"
