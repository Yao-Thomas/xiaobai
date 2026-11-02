cd /home/zynq/ui
sudo cp /tmp/apps_wifi_v3.py apps_wifi.py
sudo chown zynq:zynq apps_wifi.py
md5sum apps_wifi.py
python3 -c "import ast,io; ast.parse(io.open('apps_wifi.py',encoding='utf-8').read()); print('syntax OK')"
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  desktop: "; systemctl is-active zynq-desktop
echo "=== 打开 WiFi ==="
echo "634,400" | sudo tee /tmp/ui_tap >/dev/null
sleep 4
echo "=== 测试重置逻辑：点忘记 -> 点别处 -> 再点忘记（应再次出现确认?）==="
echo "946,239" | sudo tee /tmp/ui_tap >/dev/null
sleep 1.5
echo "  第1次点忘记（应显示确认?）"
echo "125,162" | sudo tee /tmp/ui_tap >/dev/null
sleep 3
echo "  点了重新扫描（应取消待确认）"
echo "946,239" | sudo tee /tmp/ui_tap >/dev/null
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_wifi4.raw 2>&1 | tail -1
echo "=== 确认 13A02 还在 ==="
sudo grep -c 'ssid="13A02"' /etc/wpa_supplicant/wpa_supplicant.conf