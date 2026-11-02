echo "=== 0) 重启后基本状态 ==="
uptime
echo -n "  IP: "; hostname -I
echo -n "  bitstream: "; sudo mount /dev/mmcblk0p1 /mnt/boot 2>/dev/null; md5sum /mnt/boot/system.bit | cut -d' ' -f1; sudo umount /mnt/boot 2>/dev/null
echo -n "  省电: "; iw dev $(ls /sys/class/net | grep ^wl | head -1) get power_save 2>&1
echo
echo "=== 1) 服务 ==="
for s in zynq-desktop zynq-audio zynq-agent; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done
echo
echo "=== 2) 掉线计数（本次开机）==="
sudo journalctl -b -u systemd-networkd --no-pager 2>/dev/null | grep -c "Lost carrier"