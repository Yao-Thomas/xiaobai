echo "=== 1) 当前 zynq-audio 服务定义 ==="
systemctl cat zynq-audio 2>/dev/null | grep -E "ExecStartPre|ExecStart|User|WorkingDirectory"
echo
echo "=== 2) 加一个 ExecStartPre 覆盖，把 0x0A 设成 0x00 ==="
sudo mkdir -p /etc/systemd/system/zynq-audio.service.d
sudo tee /etc/systemd/system/zynq-audio.service.d/cap-fix.conf > /dev/null <<'EOF'
# ★ 2026-10-02 加：修复采集通路
#
# 根因（实测）：
#   内核 es8388 驱动把寄存器 0x0A 设成了 0x50（LIN2/RIN2 = LINE_IN 插孔），
#   但板子上的麦克风接在 LIN1/RIN1，对应的值是 0x00。
#   结果：采集一直是近乎静音（-93 dBFS，峰值几百）。
#
# 实测对照：
#   0x0A = 0x00 -> -66 ~ -75 dBFS   正常
#   0x0A = 0x50 -> -93 dBFS 峰值 889  几乎没信号
#
# 用 i2cset -f（force）绕开内核驱动的占用，不用卸载驱动。
# 前面加 "-" 表示这一步失败也不阻止服务启动。
[Service]
ExecStartPre=-+/usr/bin/python3 /home/zynq/audio_cap_init.py
EOF
echo "  已写入 drop-in"
echo
echo "=== 3) 确认 ==="
systemctl cat zynq-audio 2>/dev/null | tail -20