TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.7; }
sudo systemctl restart zynq-desktop; sleep 13
TAP "545,555"; sleep 5
TAP "500,33"; sleep 2.5
sudo sh -c 'echo "### RUN2 ###" >> /var/log/zynq-desktop.log'
echo "=== 打 z y n q ==="
TAP "150,510"
TAP "560,420"
TAP "560,510"
TAP "150,420"
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/h1.raw >/dev/null 2>&1
echo "=== 日志 ==="
sudo awk '/### RUN2/{f=1;next} f' /var/log/zynq-desktop.log | tail -6