#!/bin/bash
#=====================================================================
#  gpu_proof.sh —— 决定性证据: 停桌面 -> FPGA GPU 独占屏幕画图 -> 截图
#=====================================================================
set -u
echo "=== [1] 彻底停掉桌面 (mask 防止自动重启) ==="
systemctl stop zynq-desktop
systemctl mask zynq-desktop >/dev/null 2>&1
sleep 2
echo -n "  桌面服务: "; systemctl is-active zynq-desktop

echo ""
echo "=== [2] 清屏 (先用 CPU 写全黑, 确认屏幕可写) ==="
python3 -c "
import mmap, os
fd = os.open('/dev/fb0', os.O_RDWR)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ|mmap.PROT_WRITE)
mm[:] = b'\x10\x10\x10' * (1024*600)
mm.flush(); mm.close(); os.close(fd)
print('  已清成深灰')
"

echo ""
echo "=== [3] ★ 用 FPGA GPU 画图 ==="
cd /home/zynq/ui
python3 gpu_show.py 2>&1 | sed 's/^/  /'

echo ""
echo "=== [4] 屏幕当前内容 (前 4 个像素的 BGR) ==="
python3 -c "
import mmap, os
fd = os.open('/dev/fb0', os.O_RDONLY)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ)
for (x,y,name) in ((100,150,'红块内'),(400,150,'绿块内'),(700,150,'蓝块内'),(500,500,'底部区域')):
    o = y*3072 + x*3
    b,g,r = mm[o], mm[o+1], mm[o+2]
    print('  %-10s (x=%4d,y=%3d) = B:%3d G:%3d R:%3d  #%02X%02X%02X' % (name,x,y,b,g,r,r,g,b))
mm.close(); os.close(fd)
"
echo "DONE-DRAW"
