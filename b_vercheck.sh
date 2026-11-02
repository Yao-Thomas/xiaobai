echo "=== 1) 服务状态 ==="
systemctl is-active zynq-desktop zynq-audio zynq-agent
echo
echo "=== 2) 音频服务 health ==="
curl -s --max-time 5 http://127.0.0.1:8767/health
echo
echo "=== 3) /state ==="
curl -s --max-time 5 http://127.0.0.1:8767/state
echo
echo "=== 4) 播放接口能否正常接受（不放音，只放一个极短的测试）==="
echo "  （按静音纪律，不实际放音，只确认服务在跑）"
echo
echo "=== 5) 回归 ==="
sudo python3 /home/zynq/regress_check.py 2>&1 | tail -22