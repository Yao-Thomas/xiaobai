echo "=== 1) agent 服务详情 ==="
systemctl status zynq-agent --no-pager -l 2>&1 | head -20
echo
echo "=== 2) agent 服务单元文件 ==="
cat /etc/systemd/system/zynq-agent.service 2>/dev/null
echo
echo "=== 3) agent 目录 ==="
ls -la /home/zynq/ui/agent/ 2>/dev/null | head -20
echo
echo "=== 4) 谁在监听 8080 / 8767 ==="
ss -tlnp 2>/dev/null | grep -E "8080|8767" || echo "  8080/8767 都没监听"
echo
echo "=== 5) agent 的日志 ==="
journalctl -u zynq-agent --no-pager -n 30 2>&1 | tail -25