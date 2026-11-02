cd /home/zynq
echo "=== 录 3 秒（S24_LE / 48k / 立体声）==="
sudo arecord -D hw:0,1 -f S24_LE -r 48000 -c 2 -d 3 /tmp/cap24.wav 2>&1 | tail -2
ls -la /tmp/cap24.wav 2>/dev/null
echo
echo "=== 分析 ==="
sudo python3 analyze_wav.py /tmp/cap24.wav