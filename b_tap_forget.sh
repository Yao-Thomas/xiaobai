echo "=== 点一次「忘记」（只高亮，不删）==="
echo "946,239" | sudo tee /tmp/ui_tap >/dev/null
sleep 2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_wifi3.raw 2>&1 | tail -1
echo
echo "=== 确认 13A02 还在配置里（没被删）==="
sudo grep -c 'ssid="13A02"' /etc/wpa_supplicant/wpa_supplicant.conf