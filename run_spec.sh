cd /home/zynq
echo "=== A) 不放音，看环境噪声频谱 ==="
sudo python3 audio_spectrum.py --secs 2 --top 8 2>&1 | tail -22
echo
echo "=== B) 放 990Hz，看能不能听到 ==="
sudo python3 audio_spectrum.py --secs 2 --play 990 --vol 55 --top 8 2>&1 | tail -24