TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.55; }
CAP() { sudo python3 /home/zynq/ui/shot_fb.py /tmp/$1.raw >/dev/null 2>&1; }

echo "=== 重开一次桌面（干净起点）==="
sudo systemctl restart zynq-desktop; sleep 12
sudo sh -c 'echo "### CLEAN RUN ###" >> /var/log/zynq-desktop.log'

echo "=== 1) 打开浏览器 ==="
TAP "545,555"; sleep 5
CAP s1

echo "=== 2) 点地址栏 ==="
TAP "500,33"; sleep 2
CAP s2

echo "=== 3) 打拼音 xianzai ==="
TAP "232,510"   # x
TAP "724,420"   # i
TAP "150,465"   # a
TAP "560,510"   # n
TAP "150,510"   # z
TAP "150,465"   # a
TAP "724,420"   # i
sleep 1
CAP s3

echo "=== 4) 点候选「现在」 ==="
TAP "118,327"; sleep 1.2
CAP s4

echo "=== 5) 截图后立刻核对当前应用 ==="
sudo awk '/### CLEAN RUN/{f=1;next} f' /var/log/zynq-desktop.log | tail -12
echo "--- 屏幕当前内容（s4 已存）---"