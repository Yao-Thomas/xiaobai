echo "=== 1) udmabuf / uio / dma 相关设备 ==="
ls -la /dev/udmabuf* /dev/uio* /dev/dma* 2>/dev/null || echo "  （没有）"
echo
echo "=== 2) CMA 预留 ==="
grep -iE "cma|CMA" /proc/meminfo 2>/dev/null
echo "  --- 内核启动参数 ---"
cat /proc/cmdline
echo
echo "=== 3) /dev/mem 能不能用（已有验证）==="
ls -la /dev/mem
echo
echo "=== 4) 内核模块 ==="
lsmod | head -10
echo "  --- 有没有 udmabuf 模块 ---"
find /lib/modules -name "*udmabuf*" -o -name "*uio*" 2>/dev/null | head -5
echo
echo "=== 5) 内存布局（DDR 大小 + 已用）==="
free -m
echo
echo "=== 6) 有没有预留的物理内存段 ==="
sudo cat /proc/iomem 2>/dev/null | grep -iE "reserved|System RAM" | head -8
echo
echo "=== 7) 上一轮示波器的 scope.c 是怎么拿内存的（参考）==="
grep -nE "mmap|/dev/mem|0x43C|phys|open\(" /home/zynq/ui/scope.py 2>/dev/null | head -10