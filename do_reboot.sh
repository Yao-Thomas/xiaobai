echo "=== 重启前记录 ==="
date
echo -n "  当前 bitstream: "; md5sum /mnt/boot/system.bit | cut -d' ' -f1
echo
echo "=== 重启 ==="
sudo sync
sudo reboot