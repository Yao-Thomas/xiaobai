cd /home/zynq
sudo python3 -c "import ast,io; ast.parse(io.open('thermal_guard.py',encoding='utf-8').read()); print('syntax OK')"
echo
echo "=== 演练新阈值 ==="
for t in 85 89 91 93 96; do
  sudo python3 thermal_guard.py --test $t | head -4
  echo
done
echo "=== 重启守护 ==="
sudo systemctl restart thermal-guard
sleep 6
systemctl is-active thermal-guard
sudo tail -4 /var/log/thermal_guard.log
echo
echo "=== 当前温度 ==="
sudo python3 thermal_guard.py --once
echo
echo "=== ★ 恢复桌面（实测停桌面不降温，没必要让它停着）==="
sudo python3 - <<'PYEOF'
# 把状态文件里的 stopped 清掉，让守护重新评估
import json, os
p = "/run/thermal/state.json"
try:
    d = json.load(open(p))
    d["stopped"] = []
    open(p,"w").write(json.dumps(d))
    print("  已清 stopped 列表")
except Exception as e:
    print("  ", e)
PYEOF
sudo systemctl start zynq-desktop 2>/dev/null
sleep 4
for s in zynq-desktop zynq-audio zynq-agent thermal-guard; do printf "  %-16s %s\n" "$s" "$(systemctl is-active $s)"; done