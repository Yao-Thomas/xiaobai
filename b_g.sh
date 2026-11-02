TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.55; }
sudo systemctl restart zynq-desktop; sleep 13
BEFORE=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo "  桌面启动: $BEFORE"

echo "=== 1) 打开浏览器 + 点地址栏 ==="
TAP "545,555"; sleep 5
TAP "500,33"; sleep 2

echo "=== 2) 打拼音 zynq 教程 (zynqjiaocheng 太长, 打 zynq) ==="
TAP "150,510"   # z
TAP "560,420"   # y
TAP "560,510"   # n
TAP "150,420"   # q
sleep 1
sudo python3 /home/zynq/ui/shot_fb.py /tmp/g1.raw >/dev/null 2>&1

echo "=== 3) 点第一个候选 ==="
TAP "118,327"; sleep 1
sudo python3 /home/zynq/ui/shot_fb.py /tmp/g2.raw >/dev/null 2>&1

echo "=== 4) 回车搜索 ==="
TAP "798,556"; sleep 12
sudo python3 /home/zynq/ui/shot_fb.py /tmp/g3.raw >/dev/null 2>&1

AFTER=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo
echo "  桌面启动: $AFTER"
[ "$BEFORE" = "$AFTER" ] && echo "  ✅ 全程桌面没被重启" || echo "  ❌ 桌面被重启了"