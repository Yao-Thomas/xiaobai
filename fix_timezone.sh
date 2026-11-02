#!/usr/bin/env bash
echo "=== 1) 改时区前 ==="
timedatectl 2>/dev/null | head -6 | sed 's/^/  /'
date '+  板子当前显示: %Y-%m-%d %H:%M:%S %Z'
echo
echo "=== 2) 设成 Asia/Shanghai ==="
sudo timedatectl set-timezone Asia/Shanghai 2>&1 | sed 's/^/  /'
sudo ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime 2>/dev/null
echo "  已设"
echo
echo "=== 3) 改完后 ==="
timedatectl 2>/dev/null | head -6 | sed 's/^/  /'
date '+  板子当前显示: %Y-%m-%d %H:%M:%S %Z (%z)'
echo
echo "=== 4) NTP 同步状态 ==="
timedatectl show 2>/dev/null | grep -iE "NTP|Synchronized|TimeUSec" | sed 's/^/  /'
echo
echo "=== 5) 让桌面的时钟立刻刷新（桌面只在有事件时重绘）==="
echo "512,300" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
echo "  已注入一次点击触发重绘"
date '+  现在: %H:%M:%S'
