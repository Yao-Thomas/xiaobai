cd /home/zynq/ui
TS=$(date +%Y%m%d_%H%M%S)
sudo cp desktop.py desktop.py.bak_beatfix_$TS
echo "  已备份: desktop.py.bak_beatfix_$TS"
sudo cp /tmp/desktop_new.py desktop.py
sudo chown zynq:zynq desktop.py
md5sum desktop.py
python3 -c "import ast,io; ast.parse(io.open('desktop.py',encoding='utf-8').read()); print('syntax OK')"
sudo systemctl restart zynq-desktop
sleep 14
echo
echo "=== ★ 验证：打开浏览器，等 40 秒，桌面不该重启 ==="
BEFORE=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo "  打开前桌面启动时间: $BEFORE"
printf '545,555' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 5
printf '500,33' | sudo tee /tmp/ui_tap >/dev/null; sync   # 点地址栏（键盘弹出）
sleep 40
AFTER=$(systemctl show zynq-desktop -p ExecMainStartTimestamp --value)
echo "  40秒后桌面启动时间: $AFTER"
if [ "$BEFORE" = "$AFTER" ]; then echo "  ✅ 桌面没被重启 —— 修复生效！"; else echo "  ❌ 桌面被重启了"; fi
echo
echo "=== 看门狗日志（最近 60 秒）==="
sudo journalctl -u desktop-watchdog --no-pager --since "-60s" 2>/dev/null | grep -E "心跳|ok|stalled" | tail -5
echo
echo "=== 心跳文件年龄 ==="
echo "  $(($(date +%s) - $(cut -d. -f1 /run/desktop_beat 2>/dev/null))) 秒"
sudo python3 /home/zynq/ui/shot_fb.py /tmp/s7.raw >/dev/null 2>&1 && echo "  已截图"