cd /home/zynq
echo "=== 1) 单次读温度 ==="
sudo python3 thermal_guard.py --once
echo
echo "=== 2) 演练各等级 ==="
for t in 70 76 82 87 92; do
  sudo python3 thermal_guard.py --test $t
  echo
done
echo "=== 3) 安全模式跑 20 秒（只看不动）==="
sudo timeout 20 python3 thermal_guard.py --no-action --interval 4 2>&1 | head -12
echo
echo "=== 4) 状态文件 ==="
sudo python3 thermal_guard.py --status