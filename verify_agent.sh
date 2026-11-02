sudo systemctl restart zynq-agent
sleep 8
echo "  zynq-agent: $(systemctl is-active zynq-agent)"
echo
echo "=== 3) 工具数确认 ==="
curl -s --max-time 10 http://127.0.0.1:8765/tools > /tmp/_t.json
python3 -c "
import json
d = json.load(open('/tmp/_t.json'))
names = [t.get('name') if isinstance(t,dict) else str(t) for t in d.get('tools',[])]
hw = sorted(n for n in names if n.startswith('hw_'))
print('  工具总数 =', len(names))
print('  硬件工具 =', len(hw))
for n in hw:
    print('     ', n)
"
echo
echo "=== 4) 名称检查（提示词修好了吗）==="
curl -s --max-time 15 -X POST -H "Content-Type: application/json" \
     -d '{"text":"你叫什么"}' http://127.0.0.1:8765/voice | head -c 400
echo