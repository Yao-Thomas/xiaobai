cd /home/zynq/ui
# 在浏览器主循环里插调试输出（临时）
sudo cp apps_browser.py /tmp/ab_dbg.py
sudo python3 - <<'PYEOF'
p = "/tmp/ab_dbg.py"
s = open(p, encoding="utf-8").read()
old = """            ev = self.touch.poll(move=True)
            if not ev:"""
new = """            ev = self.touch.poll(move=True)
            if ev:
                print("[br] EV %r  kb=%s" % (ev, self.kb is not None), flush=True)
            if not ev:"""
if old in s:
    s = s.replace(old, new, 1)
    old2 = """    def tap(self, x, y):
        # 桌面 / 退出"""
    new2 = """    def tap(self, x, y):
        print("[br] tap(%s,%s) addr=%s" % (x, y, fbui.hit(self.addr, x, y)), flush=True)
        # 桌面 / 退出"""
    if old2 in s:
        s = s.replace(old2, new2, 1)
        open(p, "w", encoding="utf-8").write(s)
        print("  已插桩")
    else:
        print("  !! tap 锚点没找到")
else:
    print("  !! 主循环锚点没找到")
PYEOF
sudo cp /tmp/ab_dbg.py apps_browser.py
sudo chown zynq:zynq apps_browser.py
sudo systemctl restart zynq-desktop
sleep 12
echo "=== 打开浏览器 ==="
printf '545,555' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 6
echo "=== 点地址栏 ==="
printf '500,33' | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 3
echo
echo "=== 日志 ==="
sudo tail -18 /var/log/zynq-desktop.log