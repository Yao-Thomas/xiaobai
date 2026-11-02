L=/var/log/zynq-desktop.log
echo "=== 1) 有没有 APP ERROR / Traceback ==="
sudo grep -nE "APP ERROR|Traceback|Exception|Error" $L | tail -20
echo
echo "=== 2) 日志里所有 browser 相关 + 出口相关 ==="
sudo grep -nE "browser|桌面.*退出|exit|ExitApp|返回" $L | tail -20
echo
echo "=== 3) 日志总行数 + 最后 30 行 ==="
sudo wc -l $L
sudo tail -30 $L