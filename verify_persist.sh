#!/usr/bin/env bash
echo "=== 验证持久化机制 ==="
echo "1) 故意把 Output 设成小值 10"
amixer -c 0 -q sset 'Output 1' 10
amixer -c 0 -q sset 'Output 2' 10
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "2) 重启音频服务（ExecStartPre 应该把它拉回 33）"
sudo systemctl restart zynq-audio
sleep 4
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left"
echo
echo "3) 模拟"开机"：只做 daemon-reload + restart，看是否稳定"
sudo systemctl restart zynq-audio
sleep 4
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "4) alsa 状态文件里的值（重启时 alsa-restore 会读它）"
sudo grep -A2 -E "name='Output 1'|name='Playback'" /var/lib/alsa/asound.state 2>/dev/null | head -20
echo
echo "5) 桌面也在跑吧"
systemctl is-active zynq-desktop
echo
echo "=== 最终状态 ==="
echo -n "  zynq-audio   : "; systemctl is-active zynq-audio
echo -n "  zynq-desktop : "; systemctl is-active zynq-desktop
echo -n "  Output 1/2   : "
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -oE "Playback [0-9]+" | head -1
