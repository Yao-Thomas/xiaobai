#!/usr/bin/env bash
echo "=== 重写 drop-in（用不展开的 heredoc）==="
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<'EOF'
# 开机把 ES8388 的增益全部拉到最大
# 2026-09-29 实测各项上限：
#   Playback(DAC数字) = 192 -> 0.00 dB   (量程 0-192)
#   Output 1/2        = 33  -> +4.50 dB  (量程 0-33)
#   0x1D Vpp_scale    = 1   -> 4.0V      (默认 0 = 3.5V，+1.16 dB)
#
# ★ 两个坑：
#   1) systemd 的 PATH 里没有 /usr/sbin，i2cget/i2cset 必须写绝对路径
#   2) 写这个文件时必须用不展开的 heredoc(<<'EOF')，否则 $(...) 会在
#      写文件时就被求值，留给 systemd 的就成了空字符串
[Service]
ExecStartPre=/bin/sh -c '/usr/bin/amixer -q -c 0 sset "Playback" 192 2>/dev/null; /usr/bin/amixer -q -c 0 sset "Output 1" 33 2>/dev/null; /usr/bin/amixer -q -c 0 sset "Output 2" 33 2>/dev/null; true'
ExecStartPre=/bin/sh -c 'v=$(/usr/sbin/i2cget -f -y 1 0x10 0x1d 2>/dev/null); if [ -n "$v" ]; then /usr/sbin/i2cset -f -y 1 0x10 0x1d $(( (v & 0xfc) | 1 )) 2>/dev/null; fi; true'
EOF
sudo systemctl daemon-reload
echo "  写好了，内容："
sudo cat /etc/systemd/system/zynq-audio.service.d/volume-max.conf | sed 's/^/    /'
echo
echo "=== 重启音频服务验证 ==="
sudo systemctl restart zynq-audio
sleep 5
echo -n "  audio: "; systemctl is-active zynq-audio
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
v=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
printf "  0x1D = %s  " "$v"
[ "$((v & 3))" = "1" ] && echo "(Vpp 4.0V ✓)" || echo "(Vpp 3.5V ✗)"
echo
echo "=== 手动补一次（如果上面还没到位）==="
if [ "$((v & 3))" != "1" ]; then
  sudo i2cset -f -y 1 0x10 0x1d $(( (v & 0xfc) | 1 ))
  v=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
  printf "  手动后 0x1D = %s  " "$v"
  [ "$((v & 3))" = "1" ] && echo "(Vpp 4.0V ✓)" || echo "(还是不行 ✗)"
fi
echo
echo "=== 把 0x1D 也写进 alsa 状态（重启也能恢复）==="
sudo alsactl store 2>&1 | sed 's/^/  /'
ls -l /var/lib/alsa/asound.state | awk '{print "  "$5" 字节  "$9}'
