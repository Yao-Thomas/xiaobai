#!/usr/bin/env bash
# 可靠地读混音器 + 建立开机自动恢复音量
echo "=== 1) 当前值（用 cget 精确读）==="
for c in 'Playback' 'Output 1' 'Output 2'; do
  v=$(amixer -c 0 cget "name='$c'" 2>/dev/null | grep -oE ': values=[0-9,]+' | head -1)
  echo "  $c  $v"
done
echo
echo "=== 2) 有没有开机恢复 ALSA 状态的服务 ==="
systemctl list-unit-files 2>/dev/null | grep -iE "alsa|sound" 
ls -l /lib/systemd/system/alsa-restore.service /etc/systemd/system/alsa-restore.service 2>/dev/null
echo
echo "=== 3) zynq-audio.service 的 drop-in ==="
cat /etc/systemd/system/zynq-audio.service.d/alsa.conf 2>/dev/null
echo
echo "=== 4) 写一个开机自动设音量的 drop-in（简单可靠）==="
sudo mkdir -p /etc/systemd/system/zynq-audio.service.d
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<'EOF'
# 开机把 ES8388 的输出音量拉到最大
# 2026-09-29: 驱动默认 Output=27(-4.5dB)，DAC 数字音量也会被播放时重写。
# 这里在服务启动前统一设到上限：Playback 192(0dB) + Output1/2 33(+4.5dB)
[Service]
ExecStartPre=/bin/sh -c 'amixer -c 0 -q sset "Playback" 192 2>/dev/null; amixer -c 0 -q sset "Output 1" 33 2>/dev/null; amixer -c 0 -q sset "Output 2" 33 2>/dev/null; true'
EOF
echo "  已写 volume-max.conf"
sudo systemctl daemon-reload
echo
echo "=== 5) 现在就设一遍并验证 ==="
amixer -c 0 -q sset 'Playback' 192
amixer -c 0 -q sset 'Output 1' 33
amixer -c 0 -q sset 'Output 2' 33
sleep 1
for c in 'Playback' 'Output 1' 'Output 2'; do
  v=$(amixer -c 0 cget "name='$c'" 2>/dev/null | grep -oE ': values=[0-9,]+' | head -1)
  echo "  $c  $v"
done
echo
echo "=== 6) 重启音频服务，验证 ExecStartPre 生效 ==="
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
for c in 'Playback' 'Output 1'; do
  v=$(amixer -c 0 cget "name='$c'" 2>/dev/null | grep -oE ': values=[0-9,]+' | head -1)
  echo "  $c  $v"
done
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
