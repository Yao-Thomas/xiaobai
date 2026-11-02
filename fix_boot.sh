#!/bin/bash
#=====================================================================
#  fix_boot.sh —— 诊断并修复"板子进不去系统"
#  怀疑: 重启后 PL 被 BOOT.BIN 重新配置(没有 GPU), 但 .gpu_addr 还在
#        -> 桌面探测 0x43CB0000 -> 访问未解码地址 -> SIGBUS -> 桌面崩溃循环
#=====================================================================
set -u

echo "=== [1] 桌面服务状态 ==="
systemctl is-active zynq-desktop
systemctl is-enabled zynq-desktop 2>&1
echo "  最近的重启次数:"
systemctl show zynq-desktop -p NRestarts 2>/dev/null

echo ""
echo "=== [2] 内核日志找 SIGBUS/崩溃 ==="
journalctl -u zynq-desktop --no-pager -n 12 2>/dev/null | tail -12
echo "  --- dmesg ---"
dmesg | grep -i -E "bus error|sigbus|desktop|segfault" | tail -6

echo ""
echo "=== [3] GPU 标记文件 ==="
if [ -f /home/zynq/.gpu_addr ]; then
    echo "  .gpu_addr 存在: $(cat /home/zynq/.gpu_addr)"
    echo "  ★ 但重启后 PL 已被 BOOT.BIN 重新配置, GPU 不在了!"
    echo "  ★ 桌面探测这个地址会触发 SIGBUS -> 崩溃循环"
    echo ""
    echo "=== [4] 移走标记文件 (让桌面回退软件渲染) ==="
    mv /home/zynq/.gpu_addr /home/zynq/.gpu_addr.disabled
    echo "  已改名为 .gpu_addr.disabled"
else
    echo "  .gpu_addr 不存在 (正常)"
fi

echo ""
echo "=== [5] 重启桌面 ==="
systemctl restart zynq-desktop
sleep 12
echo -n "  服务: "; systemctl is-active zynq-desktop
echo "  --- 日志 ---"
tail -6 /var/log/zynq-desktop.log | sed 's/^/    /'

echo ""
echo "=== [6] 屏幕内容抽样 (看桌面有没有画出来) ==="
python3 -c "
import mmap, os
fd = os.open('/dev/fb0', os.O_RDONLY)
mm = mmap.mmap(fd, 3072*600, mmap.MAP_SHARED, mmap.PROT_READ)
import collections
c = collections.Counter()
for y in range(0, 600, 37):
    for x in range(0, 1024, 41):
        o = y*3072 + x*3
        c[(mm[o+2], mm[o+1], mm[o])] += 1
mm.close(); os.close(fd)
print('  屏幕上最常见的 5 种颜色 (RGB):')
for col, n in c.most_common(5):
    print('    #%02X%02X%02X  x%d' % (col[0], col[1], col[2], n))
"
echo DONE-BOOT
