cd /home/zynq
echo "=== 温度 / 静音锁 ==="
echo -n "  温度: "; sudo python3 thermal_guard.py --once
echo "  静音锁: $([ -f /etc/zynq-silent ] && echo 锁着 || echo 未锁)"
echo
echo "=== 声学自测（990.53Hz）==="
sudo python3 acoustic_selftest.py --freq 990.53 --secs 1.2 --vol 40 2>&1 | tail -30