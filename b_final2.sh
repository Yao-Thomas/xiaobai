cd /home/zynq/ui
sudo cp /tmp/ab_clean.py apps_browser.py
sudo chown zynq:zynq apps_browser.py
md5sum apps_browser.py
python3 -c "import ast,io; ast.parse(io.open('apps_browser.py',encoding='utf-8').read()); print('syntax OK')"
echo "  （确认为无调试插桩的干净版）"
grep -c "KEY %r" apps_browser.py || echo "  已无插桩 ✓"
sudo systemctl restart zynq-desktop; sleep 13
echo
echo "=== 最终验证：打开浏览器 -> 地址栏 -> 打 xianzai -> 选「现在」 -> 回车 ==="
TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.7; }
TAP "545,555"; sleep 5
TAP "500,33"; sleep 2.5
# x i a n z a i
TAP "194,510"   # x
TAP "674,420"   # i
TAP "114,465"   # a
TAP "514,510"   # n
TAP "114,510"   # z
TAP "114,465"   # a
TAP "674,420"   # i
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k1.raw >/dev/null 2>&1
TAP "118,327"   # 点第一个候选
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k2.raw >/dev/null 2>&1
TAP "798,556"   # 回车
sleep 12
sudo python3 /home/zynq/ui/shot_fb.py /tmp/k3.raw >/dev/null 2>&1
echo "  桌面启动: $(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)"