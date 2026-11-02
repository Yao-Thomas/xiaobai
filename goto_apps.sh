#!/usr/bin/env bash
echo "=== 返回桌面，进应用页 ==="
echo "60,30" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
echo "378,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  已进入应用页"
echo
echo "=== 看当前在第几页、有哪些图标（从日志推断不了，直接截图）==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/g.raw 2>/dev/null
echo "  已抓图"
echo
echo "=== 顺便看卡农还在播吗 ==="
curl -s --max-time 5 http://127.0.0.1:8767/state; echo
