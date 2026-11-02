#!/usr/bin/env bash
echo "=== 1) 回桌面 ==="
echo "60,30" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
echo "=== 2) 打开开始菜单（左下「全部应用」）==="
echo "80,550" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo "  日志:"; sudo tail -3 /var/log/zynq-desktop.log | sed 's/^/    /'
echo
echo "=== 3) 抓图看菜单布局 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/menu.raw 2>/dev/null && echo "  ok"
echo
echo "=== 4) 清掉最近的错误日志，方便判断新错误 ==="
sudo truncate -s 0 /var/log/zynq-desktop.log 2>/dev/null || sudo cp /dev/null /var/log/zynq-desktop.log
echo "  日志已清空，接下来出现的都必然是新的"
