echo "=== 打开浏览器（点 Dock 上的「浏览器」约 545,555）==="
echo "545,555" | sudo tee /tmp/ui_tap >/dev/null
sleep 6
echo "=== 点地址栏（顶栏 y≈33，x≈400）==="
echo "400,33" | sudo tee /tmp/ui_tap >/dev/null
sleep 3
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_br1.raw 2>&1 | tail -1