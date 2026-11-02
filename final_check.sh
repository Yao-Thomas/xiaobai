echo "=== 温度趋势 ==="
echo -n "  当前: "; sudo python3 thermal_guard.py --once
echo "  守护状态:"
sudo python3 thermal_guard.py --status 2>/dev/null | head -14
echo
echo "=== 最近温度历史 ==="
sudo tail -8 /run/thermal/history.txt 2>/dev/null
echo
echo "=== 服务状态 ==="
for s in zynq-desktop zynq-audio zynq-agent thermal-guard thermal-cooldown; do
  printf "  %-18s %s\n" "$s" "$(systemctl is-active $s)"
done
echo
echo "=== agent 工具数 ==="
curl -s --max-time 8 http://127.0.0.1:8765/tools | python3 -c "
import json,sys
d = json.load(sys.stdin)
n = [t.get('name') if isinstance(t,dict) else str(t) for t in d.get('tools',[])]
print('  总数 %d，硬件工具 %d' % (len(n), len([x for x in n if x.startswith('hw_')])))
"