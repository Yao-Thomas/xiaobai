#!/bin/bash
# 配置桌面开机自启 (注意: pkill 用 [d] 技巧, 避免杀掉自己的 ssh 会话)
echo "=== [1] 停掉旧进程 ==="
pkill -9 -f "[d]esktop.py" 2>/dev/null
sleep 1
echo "ok"

echo ""
echo "=== [2] 写 systemd 服务 ==="
cat > /etc/systemd/system/zynq-desktop.service <<'EOF'
[Unit]
Description=Zynq Framebuffer Desktop
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/zynq/ui
ExecStartPre=/bin/sleep 5
ExecStartPre=/bin/sh -c 'echo 0 > /sys/class/graphics/fbcon/cursor_blink 2>/dev/null || true'
ExecStartPre=/bin/sh -c 'echo "1 4 1 7" > /proc/sys/kernel/printk || true'
ExecStart=/usr/bin/python3 -u /home/zynq/ui/desktop.py
Restart=on-failure
RestartSec=6
StandardOutput=append:/var/log/zynq-desktop.log
StandardError=append:/var/log/zynq-desktop.log

[Install]
WantedBy=multi-user.target
EOF
ls -l /etc/systemd/system/zynq-desktop.service

echo ""
echo "=== [3] 关掉 tty1 的 getty ==="
systemctl disable getty@tty1.service 2>&1 | tail -1

echo ""
echo "=== [4] 启用并启动 ==="
systemctl daemon-reload
systemctl enable zynq-desktop.service 2>&1 | tail -2
systemctl start zynq-desktop.service
sleep 10
echo "--- 状态 ---"
systemctl is-active zynq-desktop.service
pgrep -af "[d]esktop.py" || echo "(没起来!)"
echo ""
echo "--- 日志 ---"
tail -8 /var/log/zynq-desktop.log 2>/dev/null
echo AUTOSTART_DONE
