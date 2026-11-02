#!/usr/bin/env bash
echo "=== 1) 当前混音器值（重启后有没有丢）==="
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left" | head -1
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left" | head -1
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left" | head -1
echo
echo "=== 2) 强制设成最大 ==="
amixer -c 0 -q sset 'Playback' 192
amixer -c 0 -q sset 'Output 1' 33
amixer -c 0 -q sset 'Output 2' 33
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left" | head -1
echo
echo "=== 3) 让 ALSA 状态持久化（重启后自动恢复）==="
sudo alsactl store 2>&1 && echo "  alsactl store OK"
ls -l /var/lib/alsa/asound.state 2>/dev/null | awk '{print "  "$5" 字节  "$9}'
echo
echo "=== 4) 检查有没有已有的开机音量脚本 ==="
ls -l /etc/systemd/system/*audio* /etc/systemd/system/*alsa* 2>/dev/null
grep -rn "amixer" /etc/systemd/system/ 2>/dev/null | head -5
echo
echo "=== 5) 音频服务的启动依赖 ==="
systemctl cat zynq-audio 2>/dev/null | grep -E "After|Wants|Before|ExecStart"
