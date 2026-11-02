cd /home/zynq
echo "=== 修正后的解析（应该显示 -2 / 0，而不是 65535）==="
sudo python3 analyze_wav.py /tmp/cap44.wav 2>&1 | head -22