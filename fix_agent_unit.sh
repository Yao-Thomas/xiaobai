#!/bin/bash
set -e
# 用更可靠的依赖：不要 network-online.target（这板子上它不一定被拉起，
# 会导致重启后 zynq-agent 不启动 —— 实测踩到过，health 直接没有 8765）
sudo tee /etc/systemd/system/zynq-agent.service > /dev/null <<'EOF'
[Unit]
Description=系统管家小白 (Zynq onboard agent, DeepSeek-backed)
After=multi-user.target zynq-audio.service
Wants=zynq-audio.service

[Service]
Type=simple
User=zynq
Group=zynq
WorkingDirectory=/home/zynq
EnvironmentFile=-/etc/zynq-agent.env
ExecStart=/usr/bin/python3 -u -m agent.main --serve 8765
Restart=always
RestartSec=5
StandardOutput=append:/var/log/zynq-agent.log
StandardError=append:/var/log/zynq-agent.log

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable zynq-agent >/dev/null 2>&1
sudo systemctl restart zynq-agent
sleep 4
echo "--- 状态 ---"
systemctl is-active zynq-agent
systemctl is-enabled zynq-agent
curl -s --max-time 8 http://127.0.0.1:8765/health; echo
