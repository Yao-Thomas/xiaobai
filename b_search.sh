TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.6; }
echo "=== 按回车，用中文「现在」搜索 ==="
TAP "798,556"
sleep 8
sudo python3 /home/zynq/ui/shot_fb.py /tmp/s5.raw >/dev/null 2>&1
echo "=== 日志 ==="
sudo awk '/### CLEAN RUN/{f=1;next} f' /var/log/zynq-desktop.log | tail -8