cd /home/zynq/ui
TS=$(date +%Y%m%d_%H%M%S)
sudo cp apps_browser.py apps_browser.py.bak_ime_$TS
echo "  已备份: apps_browser.py.bak_ime_$TS"
sudo cp /tmp/apps_browser_new.py apps_browser.py
sudo chown zynq:zynq apps_browser.py
md5sum apps_browser.py
python3 -c "import ast,io; ast.parse(io.open('apps_browser.py',encoding='utf-8').read()); print('syntax OK')"
echo
echo "=== IME 引擎自检（板上）==="
cd /home/zynq/ui && python3 ime_cn.py 2>&1 | head -8
echo
echo "=== 重启桌面 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  desktop: "; systemctl is-active zynq-desktop