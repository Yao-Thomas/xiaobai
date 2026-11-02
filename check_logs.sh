echo "--- zynq-desktop 最近日志 ---"
sudo journalctl -u zynq-desktop -n 30 --no-pager 2>/dev/null | tail -15
echo
echo "--- zynq-audio 最近日志 ---"
sudo journalctl -u zynq-audio -n 30 --no-pager 2>/dev/null | tail -15
echo
echo "--- 现在还有 aplay 在跑吗 ---"
ps aux | grep -E "aplay" | grep -v grep | head -3
echo
echo "--- 服务状态 ---"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo