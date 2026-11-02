echo "=== 点网络卡片打开 WiFi ==="
echo "634,400" | sudo tee /tmp/ui_tap >/dev/null
sleep 4
echo "=== 截图 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_wifi.raw 2>&1 | head -2
ls -la /tmp/shot_wifi.raw