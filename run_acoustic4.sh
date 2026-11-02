cd /home/zynq
echo "=== 温度 ==="
echo -n "  "; sudo python3 thermal_guard.py --once
echo
echo "=== ★ 声学自测（修正播放设备后）==="
sudo python3 acoustic_selftest.py --freq 990.53 --secs 1.5 --vol 100 2>&1 | tail -28