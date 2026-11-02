cd /home/zynq/ui
echo "=== 打补丁（精确判据）==="
sudo python3 patch_start_bug2.py 2>&1 | sed 's/^/  /'
echo
echo "=== 重启桌面 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  desktop: "; systemctl is-active zynq-desktop
sudo tail -4 /var/log/zynq-desktop.log | sed 's/^/  /'