#!/bin/bash
echo "=== [1] Xorg 日志相关行 ==="
grep -nE "fbdev|FBDEV|AddScreen|ScreenInit|\(EE\)|Depth|visual|Fatal" /tmp/xorg.log | head -40

echo ""
echo "=== [2] Xorg 日志最后 30 行 ==="
tail -30 /tmp/xorg.log

echo ""
echo "=== [3] /dev/dri ==="
ls -l /dev/dri/ 2>&1

echo ""
echo "=== [4] framebuffer 参数 ==="
for f in name virtual_size bits_per_pixel stride; do
  echo -n "$f = "; cat /sys/class/graphics/fb0/$f
done

echo ""
echo "=== [5] 已装 X 驱动 ==="
dpkg -l | grep -E "xserver-xorg-video|xserver-xorg-input" | awk '{print $2, $3}'

echo ""
echo "=== [6] 模块 ==="
lsmod | grep -iE "drm|xlnx|fb" | head

echo ""
echo "=== [7] 内核启动参数 ==="
cat /proc/cmdline
