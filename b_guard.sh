echo "=== 1) 所有和 guard/watchdog/desktop 相关的服务 ==="
systemctl list-units --type=service --all --no-pager 2>/dev/null | grep -iE "guard|watch|desk|screen|zynq" 
echo
echo "=== 2) screen_guard 是不是在跑 ==="
ps -eo pid,etime,args | grep -iE "guard|watchdog" | grep -v grep
echo
echo "=== 3) 谁调用 systemctl restart zynq-desktop ==="
sudo grep -rln "restart zynq-desktop\|restart.*desktop" /etc/systemd/system/ /usr/local/bin/ /home/zynq/*.py /home/zynq/ui/*.py 2>/dev/null | head
echo
echo "=== 4) screen_guard.py 的关键逻辑 ==="
grep -nE "restart|systemctl|timeout|kill|def |main" /home/zynq/ui/screen_guard.py 2>/dev/null | head -25
echo
echo "=== 5) 有没有 timer ==="
systemctl list-timers --all --no-pager 2>/dev/null | head -10