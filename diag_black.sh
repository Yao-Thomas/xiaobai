#!/bin/bash
echo "=== [1] 桌面状态 ==="
systemctl is-active zynq-desktop
tail -4 /var/log/zynq-desktop.log

echo ""
echo "=== [2] DRM / 显示驱动状态 ==="
ls /sys/class/drm/ 2>/dev/null
for c in /sys/class/drm/card*/status; do
    [ -f "$c" ] && echo "  $c = $(cat $c)"
done

echo ""
echo "=== [3] framebuffer 信息 ==="
cat /sys/class/graphics/fb0/name 2>/dev/null
cat /sys/class/graphics/fb0/virtual_size 2>/dev/null
cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null

echo ""
echo "=== [4] 内存里的画面 (采样看是不是桌面) ==="
python3 -c "
import mmap, os, collections
fd = os.open('/dev/fb0', os.O_RDONLY)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ)
c = collections.Counter()
for y in range(0,600,29):
    for x in range(0,1024,31):
        o=y*3072+x*3
        c[(mm[o+2],mm[o+1],mm[o])]+=1
print('  最常见颜色:')
for col,n in c.most_common(4):
    print('    #%02X%02X%02X x%d' % (col[0],col[1],col[2],n))
mm.close(); os.close(fd)
"

echo ""
echo "=== [5] dmesg 里的显示相关 (关键!) ==="
dmesg | grep -i -E "drm|lcd|vtc|frmbuf|v_tc|pl_disp|rgb2lcd|backlight|pwm" | tail -20

echo ""
echo "=== [6] GPU 加载器日志 ==="
tail -6 /var/log/zynq-gpu-load.log 2>/dev/null
echo -n "  FPGA Manager: "; cat /sys/class/fpga_manager/fpga0/state
echo DONE-DIAG
