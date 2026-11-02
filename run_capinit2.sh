cd /home/zynq
echo "=== 只看当前状态（不改）==="
sudo python3 audio_cap_init.py --check 2>&1
echo
echo "=== 初始化 + 录音验证 ==="
sudo python3 audio_cap_init.py --test 2>&1