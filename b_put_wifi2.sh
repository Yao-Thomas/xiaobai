cd /home/zynq/ui
sudo cp /tmp/apps_wifi_v2.py apps_wifi.py
sudo chown zynq:zynq apps_wifi.py
echo "=== 校验 md5 ==="
md5sum apps_wifi.py
echo "=== 语法 ==="
python3 -c "import ast,io; ast.parse(io.open('apps_wifi.py',encoding='utf-8').read()); print('syntax OK')"
echo
echo "=== 重启桌面让改动生效 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  desktop: "; systemctl is-active zynq-desktop
echo
echo "=== 打开 WiFi App ==="
echo "634,400" | sudo tee /tmp/ui_tap >/dev/null
sleep 4
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_wifi2.raw 2>&1 | tail -1