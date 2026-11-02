#!/usr/bin/env bash
# 把 Vpp_scale=4.0V 也加进开机自动设置
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<'EOF'
# 开机把 ES8388 的增益全部拉到最大
# 2026-09-29: 实测各项上限
#   Playback(DAC数字) = 192 -> 0.00dB  (量程 0-192)
#   Output 1/2        = 33  -> +4.50dB (量程 0-33)
#   0x1D Vpp_scale    = 1   -> 4.0V    (默认 0 = 3.5V，+1.16dB)
[Service]
ExecStartPre=/bin/sh -c 'amixer -c 0 -q sset "Playback" 192 2>/dev/null; amixer -c 0 -q sset "Output 1" 33 2>/dev/null; amixer -c 0 -q sset "Output 2" 33 2>/dev/null; true'
ExecStartPre=/bin/sh -c 'v=$(i2cget -f -y 1 0x10 0x1d 2>/dev/null); [ -n "$v" ] && i2cset -f -y 1 0x10 0x1d $(( (v & 0xfc) | 1 )) 2>/dev/null; true'
EOF
sudo systemctl daemon-reload
echo "  drop-in 已更新（含 Vpp_scale）"
cat /etc/systemd/system/zynq-audio.service.d/volume-max.conf
echo
echo "=== 验证：重启音频服务后各项是否自动到位 ==="
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
printf "  0x1D = "; sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null