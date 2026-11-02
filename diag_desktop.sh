#!/bin/bash
echo "=== [1] 桌面服务状态 ==="
systemctl is-active zynq-desktop
echo -n "  启用状态: "; systemctl is-enabled zynq-desktop 2>&1
echo -n "  进程数: "; pgrep -c -f "[d]esktop.py" 2>/dev/null || echo 0

echo ""
echo "=== [2] GPU 相关的东西都清掉了吗 ==="
echo -n "  .gpu_addr: "; ls /home/zynq/.gpu_addr 2>/dev/null || echo "不存在 ✅"
echo -n "  .gpu_addr.disabled: "; ls /home/zynq/.gpu_addr.disabled 2>/dev/null || echo "不存在"
echo -n "  gpu-loader 服务: "; systemctl is-enabled zynq-gpu-loader 2>&1
echo -n "  drop-in: "; ls /etc/systemd/system/zynq-desktop.service.d/ 2>/dev/null || echo "目录不存在 ✅"

echo ""
echo "=== [3] .fb_phys 缓存 (桌面渲染的关键) ==="
if [ -f /home/zynq/.fb_phys ]; then
    echo "  存在: $(cat /home/zynq/.fb_phys)"
else
    echo "  ❌ 不存在 —— 桌面会走慢路径, 可能就是这个原因!"
fi

echo ""
echo "=== [4] 桌面日志 ==="
tail -12 /var/log/zynq-desktop.log 2>/dev/null

echo ""
echo "=== [5] framebuffer 信息 ==="
cat /sys/class/graphics/fb0/name 2>/dev/null
cat /sys/class/graphics/fb0/virtual_size 2>/dev/null
cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null

echo ""
echo "=== [6] 屏幕当前内容 (看是不是企鹅) ==="
python3 -c "
import mmap, os, collections
fd = os.open('/dev/fb0', os.O_RDONLY)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ)
c = collections.Counter()
for y in range(0,600,23):
    for x in range(0,1024,29):
        o=y*3072+x*3
        c[(mm[o+2],mm[o+1],mm[o])]+=1
print('  最常见颜色 (RGB):')
for col,n in c.most_common(5):
    print('    #%02X%02X%02X  x%d' % (col[0],col[1],col[2],n))
mm.close(); os.close(fd)
"
echo DONE
