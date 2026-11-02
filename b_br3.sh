echo "=== 1) 清空日志标记 ==="
sudo sh -c 'echo "### MARK $(date +%T) ###" >> /var/log/zynq-desktop.log'
echo
echo "=== 2) 注入点击地址栏（用 printf 确保写入）==="
printf '500,33' | sudo tee /tmp/ui_tap >/dev/null
sync
ls -la /tmp/ui_tap 2>/dev/null || echo "  (文件已被消费)"
sleep 2.5
echo
echo "=== 3) 再注入一次，并立刻检查 ==="
printf '600,33' | sudo tee /tmp/ui_tap >/dev/null
sync
sleep 2
echo
echo "=== 4) 截图 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_br3.raw 2>&1 | tail -1
echo
echo "=== 5) 日志（MARK 之后的部分）==="
sudo awk '/### MARK/{f=1;next} f' /var/log/zynq-desktop.log | tail -20