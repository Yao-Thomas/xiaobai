cd /home/zynq
echo "=== 温度 ==="
echo -n "  "; sudo python3 thermal_guard.py --once
echo
echo "=== ★ 扫频测试（8 个频点）==="
sudo python3 acoustic_selftest.py --sweep --secs 1.2 --vol 100 2>&1 | tail -30