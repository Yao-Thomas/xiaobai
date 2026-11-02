echo "=== 恢复音频服务 ==="
sudo systemctl start zynq-audio
sleep 5
for s in zynq-desktop zynq-audio zynq-agent thermal-guard; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done
echo
echo "=== 最终温度状态 ==="
sudo python3 /home/zynq/thermal_guard.py --status
echo
echo "=== 温度历史（守护记录的）==="
sudo tail -12 /run/thermal/history.txt 2>/dev/null