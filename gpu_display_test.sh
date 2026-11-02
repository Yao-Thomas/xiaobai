#!/bin/bash
#=====================================================================
#  gpu_display_test.sh —— 决定性测试: GPU 画的东西 LCD 上看得见吗?
#  步骤: 停桌面(独占屏幕) -> GPU 刷青色 -> 等你看 -> 恢复桌面
#=====================================================================
set -u
echo "=== [1] 停掉桌面 (让 GPU 独占屏幕, 不然会被桌面重绘覆盖) ==="
systemctl stop zynq-desktop
sleep 2
systemctl mask zynq-desktop >/dev/null 2>&1
echo -n "  桌面: "; systemctl is-active zynq-desktop

echo ""
echo "=== [2] 取显存物理地址 ==="
PHYS=$(cat /home/zynq/.fb_phys 2>/dev/null)
echo "  物理地址 = $PHYS"

echo ""
echo "=== [3] ★ 用 FPGA GPU 刷整屏青色 ==="
python3 -c "
import sys, time
sys.path.insert(0,'/home/zynq/ui')
from gpu import GPU
phys = int(open('/home/zynq/.fb_phys').read().strip(), 0)
g = GPU(0x43CB0000, verbose=False)
if not g.probe():
    print('  ❌ GPU 不在'); sys.exit(1)
print('  GPU 存在 ✅')

# 1. 整屏刷青色 (R=0 G=C0 B=FF -> 亮青蓝)
g.clear_error()
g.wr(0x08, phys); g.wr(0x0C, 3072)
g.wr(0x10, (0<<16)|0); g.wr(0x14, (1023<<16)|599)
g.wr(0x18, 0xFFC000)     # 注意: 内部格式 {R,G,B} -> 0xFFC000 = R=FF G=C0 B=00 橙黄
g.wr(0x04, 0); g.wr(0x00, 1)
t0=time.time()
while time.time()-t0 < 3:
    if g.rd(0x1C) >= 614400: break
    time.sleep(0.005)
dt=(time.time()-t0)*1000
print('  整屏填充: %d 像素, %.1f ms' % (g.rd(0x1C), dt))

# 2. 中间画一条红线
g.clear_error()
g.wr(0x10, (0<<16)|300); g.wr(0x14, (1023<<16)|300)
g.wr(0x18, 0x0000FF)     # R=00 G=00 B=FF -> 蓝色
g.wr(0x04, 1); g.wr(0x00, 1)
time.sleep(0.4)
print('  画横线: %d 像素' % g.rd(0x1C))

# 3. 左上角画个方块
g.clear_error()
g.wr(0x10, (50<<16)|50); g.wr(0x14, (250<<16)|200)
g.wr(0x18, 0x00FF00)     # R=00 G=FF B=00 -> 绿色
g.wr(0x04, 0); g.wr(0x00, 1)
time.sleep(0.4)
print('  画方块: %d 像素' % g.rd(0x1C))
g.close()
print('  STATUS=0x%X (0=无错误)' % g.rd(0x20))
" 2>/dev/null

echo ""
echo "=== [4] 回读显存确认数据写进去了 ==="
python3 -c "
import mmap, os
fd=os.open('/dev/fb0',os.O_RDONLY)
mm=mmap.mmap(fd,3072*600,mmap.MAP_SHARED,mmap.PROT_READ)
for (x,y,n) in ((512,100,'上半屏(应橙黄)'),(512,300,'横线处(应蓝)'),(150,120,'方块内(应绿)'),(900,500,'右下(应橙黄)')):
    o=y*3072+x*3
    print('  %-16s = #%02X%02X%02X' % (n, mm[o+2],mm[o+1],mm[o]))
mm.close(); os.close(fd)
"
echo ""
echo "★★★ 请看板子屏幕: 是橙黄色底 + 蓝线 + 绿方块吗? ★★★"
echo "（保持这个画面 30 秒, 然后我会恢复桌面）"
sleep 3
echo DONE-DISPLAY-TEST
