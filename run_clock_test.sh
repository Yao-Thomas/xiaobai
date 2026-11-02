cd /home/zynq/ui
echo "=== 板上 apps_clock.py 里还有没有 rounded_rectangle 调用 ==="
grep -n "rounded_rectangle" apps_clock.py | sed 's/^/  /'
echo
echo "=== 单独跑测试 ==="
sudo python3 test_clock_app.py 2>&1 | tail -35