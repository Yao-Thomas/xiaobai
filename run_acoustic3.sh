cd /home/zynq
echo "=== 运行前 ==="
echo -n "  温度: "; sudo python3 thermal_guard.py --once
sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([0x0A])); print('  0x0A = 0x%02X (0x00=麦克风)' % os.read(fd,1)[0]); os.close(fd)
"
echo
echo "=== 声学自测（990.53Hz，音量 50）==="
sudo python3 acoustic_selftest.py --freq 990.53 --secs 1.2 --vol 50 2>&1 | tail -26