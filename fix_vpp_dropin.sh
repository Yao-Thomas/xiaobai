#!/usr/bin/env bash
echo "=== 1) i2c 工具在哪 ==="
for t in i2cget i2cset amixer; do
  p=$(command -v $t 2>/dev/null)
  echo "  $t -> ${p:-没找到}"
done
echo
echo "=== 2) root 的默认 PATH 里有没有那些目录 ==="
sudo sh -c 'echo "  PATH=$PATH"'
echo
echo "=== 3) 现有 drop-in 内容 ==="
sudo cat /etc/systemd/system/zynq-audio.service.d/volume-max.conf | sed 's/^/  /'
echo
echo "=== 4) 用绝对路径重写 drop-in ==="
I2CGET=$(command -v i2cget 2>/dev/null || echo /usr/sbin/i2cget)
I2CSET=$(command -v i2cset 2>/dev/null || echo /usr/sbin/i2cset)
AMIXER=$(command -v amixer 2>/dev/null || echo /usr/bin/amixer)
echo "  用: $I2CGET  $I2CSET  $AMIXER"
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<EOF
# 开机把 ES8388 的增益全部拉到最大
# 2026-09-29 实测各项上限：
#   Playback(DAC数字) = 192 -> 0.00 dB   (量程 0-192)
#   Output 1/2        = 33  -> +4.50 dB  (量程 0-33)
#   0x1D Vpp_scale    = 1   -> 4.0V      (默认 0 = 3.5V，+1.16 dB)
# ★ 必须写绝对路径：systemd 的 PATH 里没有 /usr/sbin，i2cget/i2cset 会找不到
[Service]
ExecStartPre=/bin/sh -c '$AMIXER -q -c 0 sset "Playback" 192 2>/dev/null; $AMIXER -q -c 0 sset "Output 1" 33 2>/dev/null; $AMIXER -q -c 0 sset "Output 2" 33 2>/dev/null; true'
ExecStartPre=/bin/sh -c 'v=$($I2CGET -f -y 1 0x10 0x1d 2>/dev/null); [ -n "\$v" ] && $I2CSET -f -y 1 0x10 0x1d \$(( (v & 0xfc) | 1 )) 2>/dev/null; true'
EOF
sudo systemctl daemon-reload
echo "  已重写"
sudo cat /etc/systemd/system/zynq-audio.service.d/volume-max.conf | sed 's/^/  /'
echo
echo "=== 5) 重启音频服务验证 ==="
sudo systemctl restart zynq-audio
sleep 5
echo -n "  audio: "; systemctl is-active zynq-audio
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
printf "  0x1D = %s  " "$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)"
v=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
[ "$((v & 3))" = "1" ] && echo "(Vpp 4.0V ✓)" || echo "(Vpp 还是 3.5V ✗)"
echo
echo "=== 6) 服务日志里有没有 drop-in 的报错 ==="
sudo journalctl -u zynq-audio -n 12 --no-pager 2>/dev/null | tail -8 | sed 's/^/  /'
