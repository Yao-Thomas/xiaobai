TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.55; }
BEFORE=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo "  桌面启动: $BEFORE"

echo "=== 打拼音 xianzai ==="
TAP "232,510"; TAP "724,420"; TAP "150,465"; TAP "560,510"
TAP "150,510"; TAP "150,465"; TAP "724,420"
sleep 1.2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/f1.raw >/dev/null 2>&1

echo "=== 点候选「现在」 ==="
TAP "118,327"
sleep 1.2
sudo python3 /home/zynq/ui/shot_fb.py /tmp/f2.raw >/dev/null 2>&1

echo "=== 按回车搜索 ==="
TAP "798,556"
sleep 10
sudo python3 /home/zynq/ui/shot_fb.py /tmp/f3.raw >/dev/null 2>&1

AFTER=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo
echo "  桌面启动: $AFTER"
[ "$BEFORE" = "$AFTER" ] && echo "  ✅ 全程桌面没被重启" || echo "  ❌ 桌面被重启了"
echo
echo "=== 浏览器日志 ==="
sudo tail -6 /var/log/zynq-desktop.log