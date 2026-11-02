echo "=== 1) addr 矩形定义 ==="
grep -nE "self\.addr" /home/zynq/ui/apps_browser.py | head -8
echo
echo "=== 2) 桌面日志尾部（看有没有异常）==="
sudo tail -25 /var/log/zynq-desktop.log
echo
echo "=== 3) 再点一次地址栏，然后立刻截图 ==="
echo "500,33" | sudo tee /tmp/ui_tap >/dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_br2.raw 2>&1 | tail -1