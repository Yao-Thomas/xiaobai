#!/usr/bin/env bash
# 撤掉我加的一切，恢复到我介入之前的状态，看声音回不回来
echo "=== 0) 先记录现状 ==="
echo -n "  uptime: "; uptime -p 2>/dev/null || uptime
echo "  我的 drop-in:"
ls -l /etc/systemd/system/zynq-audio.service.d/ 2>/dev/null | tail -3
echo -n "  alsa 状态文件: "; ls -l /var/lib/alsa/asound.state 2>/dev/null | awk '{print $5" 字节  "$6" "$7" "$8}'
echo
echo "=== 1) 撤掉 drop-in ==="
sudo rm -f /etc/systemd/system/zynq-audio.service.d/volume-max.conf
sudo systemctl daemon-reload
echo "  已删 volume-max.conf"
ls /etc/systemd/system/zynq-audio.service.d/ 2>/dev/null
echo
echo "=== 2) 重启音频服务 ==="
sudo systemctl restart zynq-audio
sleep 4
echo -n "  is-active: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 3) 手动设音量（drop-in 没了要自己设）==="
amixer -c 0 -q sset 'Playback' 192 2>/dev/null
amixer -c 0 -q sset 'Output 1' 33 2>/dev/null
amixer -c 0 -q sset 'Output 2' 33 2>/dev/null
sleep 1
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 4) 关键寄存器 ==="
printf "  "
for r in 0x00 0x01 0x02 0x1a 0x1b 0x27 0x2a 0x2e 0x2f 0x30 0x31; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
echo
echo "########  放提示音 + 小星星，请听  ########"
aplay -q /home/zynq/Music/提示音.wav
echo "  --- 提示音放完 ---"
sleep 1.5
aplay -q /home/zynq/Music/03_小星星.wav
echo "  --- 小星星放完 ---"
echo
echo "=== 5) 播放后寄存器 ==="
printf "  "
for r in 0x1a 0x1b 0x2e 0x30; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
