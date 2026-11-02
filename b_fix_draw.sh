cd /home/zynq/ui
sudo cp /tmp/ab2.py apps_browser.py
sudo chown zynq:zynq apps_browser.py
md5sum apps_browser.py
python3 -c "import ast,io; ast.parse(io.open('apps_browser.py',encoding='utf-8').read()); print('syntax OK')"
# 去掉调试插桩的版本已覆盖，重启桌面
sudo systemctl restart zynq-desktop
sleep 12
echo "=== 打开浏览器 ==="
printf '545,555' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 6
echo "=== 点地址栏 ==="
printf '500,33' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 2.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_br5.raw 2>&1 | tail -1