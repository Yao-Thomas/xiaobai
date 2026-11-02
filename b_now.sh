echo "=== 1) 立即状态 ==="
date
uptime
echo "  温度: $(sudo python3 /home/zynq/thermal_guard.py --once 2>/dev/null) °C"
echo
echo "=== 2) 服务 ==="
for s in zynq-desktop zynq-audio zynq-agent thermal-guard; do
  printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"
done
echo
echo "=== 3) 实验脚本还在吗 ==="
ps -eo pid,etime,args | grep -E "[t]hermal_exp|[t]hermal_guard" 
echo
echo "=== 4) 守护日志尾部 ==="
sudo tail -8 /var/log/thermal_guard.log
echo
echo "=== 5) ★ 先把守护起回来 ==="
sudo systemctl start thermal-guard
sleep 3
echo "  thermal-guard: $(systemctl is-active thermal-guard)"
sudo python3 /home/zynq/thermal_guard.py --status