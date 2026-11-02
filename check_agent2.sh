echo "=== 1) agent 包位置 ==="
ls -la /home/zynq/agent/ 2>/dev/null | head -20
echo
echo "=== 2) 端口 8765 ==="
ss -tlnp 2>/dev/null | grep 8765 || echo "  8765 未监听"
echo
echo "=== 3) 试 API ==="
echo -n "  /tools  → "
curl -s --max-time 5 http://127.0.0.1:8765/tools | head -c 300
echo
echo
echo -n "  /tools 工具数 → "
curl -s --max-time 5 http://127.0.0.1:8765/tools | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count'))" 2>/dev/null || echo "解析失败"
echo
echo "=== 4) agent 日志尾部 ==="
tail -20 /var/log/zynq-agent.log 2>/dev/null || sudo tail -20 /var/log/zynq-agent.log 2>/dev/null