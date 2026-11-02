echo "=== 1) ALSA 声卡 ==="
cat /proc/asound/cards
echo
echo "=== 2) 录音设备 ==="
arecord -l 2>&1 | head -12
echo
echo "=== 3) 播放设备 ==="
aplay -l 2>&1 | head -8
echo
echo "=== 4) 当前 mixer 状态（只列有意义的）==="
sudo amixer -c 0 contents 2>/dev/null | grep -E "name=|Capture|Playback|\[on\]|\[off\]" | head -40