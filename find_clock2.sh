#!/usr/bin/env bash
echo "=== 返回 → 应用 ==="
echo "60,30"  | sudo tee /tmp/ui_tap > /dev/null
sleep 2.5
echo "378,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  已进应用页"
echo
echo "=== 抓图 1（当前页）==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/pg1.raw 2>/dev/null
echo "  ok"
echo
echo "=== 切到下一页看看 ==="
echo "900,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 2.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/pg2.raw 2>/dev/null
echo "  ok"
echo
echo "=== 日志 ==="
sudo tail -5 /var/log/zynq-desktop.log | sed 's/^/  /'
