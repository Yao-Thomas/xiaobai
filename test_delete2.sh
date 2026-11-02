#!/usr/bin/env bash
echo "=== 0) 确认测试文件存在 ==="
ls -l "/home/zynq/Music/zz_删除测试.wav" 2>/dev/null | awk '{print "  "$5" 字节"}'
echo
echo "=== 1) 点「刷新」让列表包含测试文件（x≈324, y≈84）==="
echo "324,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 2.5
sudo tail -3 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
echo "=== 2) 点第 1 行（应该是最新的静音文件，播 1 秒）==="
echo "400,131" | sudo tee /tmp/ui_tap > /dev/null
sleep 4
echo "  等播放结束"
sudo tail -2 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
echo "=== 3) 点「删除」第一次（应只提示）==="
echo "383,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/confirm.raw 2>/dev/null
echo "  已抓确认提示图"
echo
echo "=== 4) 点「删除」第二次（应真删）==="
echo "383,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
echo
echo "=== 5) 结果 ==="
if [ -f "/home/zynq/Music/zz_删除测试.wav" ]; then
  echo "  ✗ 还在"
else
  echo "  ✓ 已删除 —— 「删除」按钮功能正常"
fi
echo
echo "=== 6) 剩余文件 ==="
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{printf "  %8.0f KB  %s\n", $5/1024, $9}'
echo
echo "=== 7) 桌面日志尾部 ==="
sudo tail -4 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
sudo python3 /home/zynq/ui/shot_fb.py /tmp/after.raw 2>/dev/null
