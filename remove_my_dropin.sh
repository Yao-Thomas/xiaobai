#!/usr/bin/env bash
echo "=== 1) 撤掉我加的 drop-in ==="
ls -l /etc/systemd/system/zynq-audio.service.d/ 2>/dev/null
sudo rm -f /etc/systemd/system/zynq-audio.service.d/volume-max.conf
echo "  已删除 volume-max.conf"
ls -l /etc/systemd/system/zynq-audio.service.d/ 2>/dev/null
echo
echo "=== 2) daemon-reload + 重启音频服务 ==="
sudo systemctl daemon-reload
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 3) 手动把音量设到最大（因为 drop-in 没了）==="
amixer -c 0 -q sset 'Playback' 192
amixer -c 0 -q sset 'Output 1' 33
amixer -c 0 -q sset 'Output 2' 33
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 4) 关键寄存器 ==="
for r in 0x1a 0x1b 0x2e 0x30 0x27 0x2a 0x02 0x00 0x01; do
  printf "  0x%s=%s" "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
echo
echo "=== 5) 放 3 秒（请听）==="
aplay -q /home/zynq/Music/提示音.wav
echo "  提示音放完"
sleep 1
aplay -q /home/zynq/Music/03_小星星.wav
echo "  小星星放完"
echo
echo "=== 6) 播放后的寄存器（看有没有被改）==="
for r in 0x1a 0x1b 0x2e 0x30; do
  printf "  0x%s=%s" "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
