cd /home/zynq
echo "=== A) 按 44100 录 3 秒并分析 ==="
sudo rm -f /tmp/cap44.wav
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 3 /tmp/cap44.wav 2>&1 | head -2
ls -la /tmp/cap44.wav
echo
sudo python3 analyze_wav.py /tmp/cap44.wav