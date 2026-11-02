cd /home/zynq
echo "=== 运行前状态 ==="
echo -n "  温度: "; sudo python3 thermal_guard.py --once
echo "  静音锁: $([ -f /etc/zynq-silent ] && echo '★ 锁着（会拒绝放音）' || echo '未锁')"
echo
echo "=== 声学自测 ==="
sudo python3 acoustic_selftest.py --freq 990.53 --secs 1.2 --vol 40 2>&1