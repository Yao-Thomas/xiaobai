sudo cp /tmp/apps_wifi_new.py /home/zynq/ui/apps_wifi.py
sudo chown zynq:zynq /home/zynq/ui/apps_wifi.py
echo "=== 校验（对比 md5）==="
md5sum /home/zynq/ui/apps_wifi.py
echo "=== 语法 ==="
python3 -c "import ast,io; ast.parse(io.open('/home/zynq/ui/apps_wifi.py',encoding='utf-8').read()); print('syntax OK')"
echo "=== 关键改动 ==="
grep -n "def set_power_save\|networkctl" /home/zynq/ui/apps_wifi.py | head