#!/usr/bin/env bash
echo "=== 1) 重启桌面到干净状态 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  is-active: "; systemctl is-active zynq-desktop
echo
echo "=== 2) 用官方 /tmp/ui_tap 注入：点 Dock 的「音乐」 ==="
echo "656,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 4
echo "  注入完成"
echo
echo "=== 3) 桌面日志尾部（看有没有 [dock] music / [music]）==="
sudo tail -6 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
echo "=== 4) 音乐 App 是否被打开（有没有 APP ERROR）==="
sudo grep -a -c "APP ERROR" /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  APP ERROR 累计次数: /'
sudo tail -40 /var/log/zynq-desktop.log 2>/dev/null | grep -a -A8 "APP ERROR" | tail -12 | sed 's/^/  /'
