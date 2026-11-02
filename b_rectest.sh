cd /home/zynq
echo "=== 8767 上实际跑的是哪个脚本 ==="
sudo cat /proc/5423/cmdline 2>/dev/null | tr '\0' ' '; echo
echo
sudo python3 test_record_api.py 2>&1