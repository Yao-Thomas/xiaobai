TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.6; }
echo "=== 点候选「现在」(约 118,327) ==="
TAP "118,327"
sleep 1
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_py2.raw 2>&1 | tail -1
echo
echo "=== 点回车搜索 (约 798,556) ==="
TAP "798,556"
sleep 6
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_py3.raw 2>&1 | tail -1
echo
echo "=== 浏览器日志 ==="
sudo tail -8 /var/log/zynq-desktop.log