echo "=== 1) 有几个 thermal_guard 进程 ==="
ps -eo pid,etime,args | grep "[t]hermal_guard"
echo
echo "=== 2) 杀掉多余的（只留 systemd 起的那个）==="
MAIN=$(systemctl show thermal-guard -p MainPID --value)
echo "  服务 MainPID=$MAIN"
for p in $(pgrep -f "[t]hermal_guard.py"); do
  if [ "$p" != "$MAIN" ]; then
    echo "  杀掉多余 pid=$p"
    sudo kill -9 $p 2>/dev/null
  fi
done
sleep 2
echo "  剩余: $(pgrep -f '[t]hermal_guard.py' | tr '\n' ' ')"
echo
echo "=== 3) 温度趋势文件 ==="
cat /tmp/temptrend.txt 2>/dev/null | head -20
echo
echo "=== 4) 当前温度 + 负载 ==="
sudo python3 /home/zynq/thermal_guard.py --once
cat /proc/loadavg