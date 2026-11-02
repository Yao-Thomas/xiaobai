L=/var/log/zynq-desktop.log
echo "=== 步骤1: 打开浏览器 ==="
printf '545,555' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 6
sudo tail -4 $L
echo
echo "=== 步骤2: 点地址栏 (500,33) ==="
sudo sh -c "echo '### TAP1 ###' >> $L"
printf '500,33' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 3
sudo awk '/### TAP1/{f=1;next} f' $L | tail -8
echo
echo "=== 步骤3: 截图 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_br4.raw 2>&1 | tail -1
echo
echo "=== 步骤4: 进程还在吗 ==="
pgrep -af "desktop.py" | head -2
ps -eo pid,etime,args | grep -E "python3.*(desktop|browser)" | grep -v grep | head -3