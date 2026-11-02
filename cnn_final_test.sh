echo "=== 板子状态 ==="
uptime
echo -n "  IP: "; hostname -I
echo -n "  bitstream: "; sudo mount /dev/mmcblk0p1 /mnt/boot 2>/dev/null; md5sum /mnt/boot/system.bit | cut -d' ' -f1; sudo umount /mnt/boot 2>/dev/null
echo
echo "=== ★ CNN 端到端测试 ==="
cd /home/zynq
sudo python3 cnn_linux.py 2>&1