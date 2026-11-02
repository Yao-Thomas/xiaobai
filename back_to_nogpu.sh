#!/bin/bash
#=====================================================================
#  back_to_nogpu.sh —— 彻底回到"无 GPU"干净状态
#=====================================================================
set -u
echo "=== [1] 停桌面 (避免继续崩溃循环) ==="
systemctl stop zynq-desktop
sleep 2

echo ""
echo "=== [2] 删掉所有 GPU 标记 (它在撒谎!) ==="
for f in /home/zynq/.gpu_addr /home/zynq/.gpu_addr.disabled; do
    if [ -e "$f" ]; then rm -f "$f"; echo "  已删除 $f"; fi
done

echo ""
echo "=== [3] 确认 GPU 加载器彻底禁掉 ==="
systemctl disable zynq-gpu-loader 2>&1 | tail -1
rm -f /etc/systemd/system/zynq-desktop.service.d/*.conf 2>/dev/null
rmdir /etc/systemd/system/zynq-desktop.service.d 2>/dev/null
systemctl daemon-reload
echo -n "  loader 状态: "; systemctl is-enabled zynq-gpu-loader 2>&1

echo ""
echo "=== [4] 确认 PL 里是原始 bitstream (原始设计里没有 GPU) ==="
echo -n "  探测 0x43CB0000 (应该会失败, 这是正常的): "
# 放到子进程, 万一 SIGBUS 也只死子进程
python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
try:
    from gpu import GPU
    g = GPU(0x43CB0000, verbose=False)
    print('存在' if g.probe() else '不存在 (符合预期 ✅)')
    g.close()
except Exception as e:
    print('不存在 (符合预期 ✅)')
" 2>/dev/null || echo "不存在 (符合预期 ✅)"

echo ""
echo "=== [5] 启动桌面 (纯软件渲染) ==="
systemctl start zynq-desktop
sleep 14
echo -n "  服务: "; systemctl is-active zynq-desktop
echo -n "  进程数: "; pgrep -c -f "[d]esktop.py" || echo 0
echo "  --- 日志 ---"
tail -8 /var/log/zynq-desktop.log | sed 's/^/    /'

echo ""
echo "=== [6] 屏幕内容 (应该变成桌面壁纸的深蓝色调) ==="
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
for col,n in c.most_common(6):
    print('    #%02X%02X%02X  x%d' % (col[0],col[1],col[2],n))
mm.close(); os.close(fd)
"
echo DONE-NOGPU
