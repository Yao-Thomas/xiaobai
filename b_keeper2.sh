cd /home/zynq
echo "=== 用 PL 工具的三个值一起纠正，测 ALSA 采集 ==="
sudo python3 cap_keeper.py --regs 0x03=0x59,0x0A=0x00,0x0D=0x0C 2>&1