#!/bin/sh
# run_acoustic_final.sh —— 声学自测（今天修了两处：播放设备 + 0x0A）
echo "======================================================"
echo " 声学自测（验证今天的修复）"
echo "======================================================"
echo
echo "--- 前置检查 ---"
echo -n "  温度: "; sudo python3 /home/zynq/thermal_guard.py --once
echo -n "  静音锁: "; [ -f /etc/zynq-silent ] && echo "★ 锁着（会拒绝放音）" || echo "未锁"
sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([0x0A])); print('  ES8388 0x0A = 0x%02X （0x00=麦克风）' % os.read(fd,1)[0]); os.close(fd)
"
echo
echo "--- 单个频点（990.53 Hz）---"
sudo python3 /home/zynq/acoustic_selftest.py --freq 990.53 --secs 1.5 --vol 80 2>&1 | tail -12
echo
echo "--- 扫频 8 点 ---"
sudo python3 /home/zynq/acoustic_selftest.py --sweep --secs 1.2 --vol 80 2>&1 | tail -16
echo
echo "--- 音量对比（看饱和点在哪）---"
for v in 40 70 100 140; do
  echo "  vol=$v:"
  sudo python3 /home/zynq/acoustic_selftest.py --freq 990.53 --secs 1.2 --vol $v 2>&1 | grep -E "基线 RMS|放音 RMS|能量比" | sed 's/^/    /'
done
echo
echo "--- ★ JSON 输出（服务里用的）---"
sudo python3 /home/zynq/acoustic_selftest.py --freq 990.53 --secs 1.2 --vol 80 --json 2>&1 | grep "__JSON__" | head -c 500
echo
