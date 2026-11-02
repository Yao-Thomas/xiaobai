#!/usr/bin/env bash
echo "=== 1) 确认 zynq 用户能不能写 i2c ==="
ls -l /dev/i2c-* 2>/dev/null | sed 's/^/  /'
echo -n "  zynq 在哪些组: "; id zynq 2>/dev/null | sed 's/^/    /'
echo
echo "=== 2) 重写 drop-in：用 + 前缀让 I2C 那条以 root 跑 ==="
sudo tee /etc/systemd/system/zynq-audio.service.d/volume-max.conf > /dev/null <<'EOF'
# 开机把 ES8388 的增益全部拉到最大
# 2026-09-29 实测各项上限：
#   Playback(DAC数字) = 192 -> 0.00 dB   (量程 0-192)
#   Output 1/2        = 33  -> +4.50 dB  (量程 0-33)
#   0x1D Vpp_scale    = 1   -> 4.0V      (默认 0 = 3.5V，+1.16 dB)
#
# ★ 三个坑，都踩过了：
#   1) systemd 的 PATH 没有 /usr/sbin -> i2cget/i2cset 要写绝对路径
#   2) 写这个文件必须用不展开的 heredoc(<<'EOF')，否则 $(...) 写文件时就被求值
#   3) 本服务 User=zynq，而 /dev/i2c-1 需要 root -> 那条 ExecStartPre 要加 "+"
#      前缀才会以 root 身份执行（amixer 不需要，zynq 在 audio 组里）
[Service]
ExecStartPre=/bin/sh -c '/usr/bin/amixer -q -c 0 sset "Playback" 192 2>/dev/null; /usr/bin/amixer -q -c 0 sset "Output 1" 33 2>/dev/null; /usr/bin/amixer -q -c 0 sset "Output 2" 33 2>/dev/null; true'
ExecStartPre=+/bin/sh -c 'v=$(/usr/sbin/i2cget -f -y 1 0x10 0x1d 2>/dev/null); if [ -n "$v" ]; then /usr/sbin/i2cset -f -y 1 0x10 0x1d $(( (v & 0xfc) | 1 )) 2>/dev/null; fi; true'
EOF
sudo systemctl daemon-reload
echo "  已重写（I2C 那条带 + 前缀）"
echo
echo "=== 3) 先把 0x1D 恢复成 3.5V，再看服务能不能自动拉成 4.0V ==="
sudo i2cset -f -y 1 0x10 0x1d 0x1c
printf "  重置后 0x1D = %s\n" "$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)"
echo
echo "=== 4) 重启服务，看 drop-in 生不生效 ==="
sudo systemctl restart zynq-audio
sleep 5
v=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
printf "  重启后 0x1D = %s  " "$v"
[ "$((v & 3))" = "1" ] && echo "(Vpp 4.0V ✓ 自动生效了)" || echo "(还是 3.5V ✗)"
echo
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo -n "  audio: "; systemctl is-active zynq-audio
echo
echo "=== 5) 服务日志 ==="
sudo journalctl -u zynq-audio -n 10 --no-pager 2>/dev/null | tail -6 | sed 's/^/  /'
