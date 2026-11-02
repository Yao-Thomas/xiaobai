# 打开 WiFi App：先回桌面，再点 WiFi 图标
echo "=== 当前桌面截图 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_now.raw 2>&1 | head -3
ls -la /tmp/shot_now.raw 2>/dev/null
echo
echo "=== 桌面进程在吗 ==="
pgrep -af desktop.py | head -2