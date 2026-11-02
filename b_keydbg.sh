cd /home/zynq/ui
sudo cp apps_browser.py /tmp/ab3.py
sudo python3 - <<'PYEOF'
p = "/tmp/ab3.py"
s = open(p, encoding="utf-8").read()
old = """            elif c:
                # ★ 拼音模式下字母进缓冲，不直接上屏
                if self.pinyin and c.isalpha():"""
new = """            elif c:
                print("[br] KEY %r pinyin=%s py=%r input=%r" % (c, self.pinyin, self.py, self.input), flush=True)
                # ★ 拼音模式下字母进缓冲，不直接上屏
                if self.pinyin and c.isalpha():"""
if old in s:
    s = s.replace(old, new, 1)
    open(p,"w",encoding="utf-8").write(s)
    print("  已插桩")
else:
    print("  !! 锚点没找到")
PYEOF
sudo cp /tmp/ab3.py apps_browser.py
sudo chown zynq:zynq apps_browser.py
sudo systemctl restart zynq-desktop; sleep 13
TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.6; }
TAP "545,555"; sleep 5
TAP "500,33"; sleep 2
sudo sh -c 'echo "### KEYDBG ###" >> /var/log/zynq-desktop.log'
TAP "150,510"; TAP "560,420"; TAP "560,510"; TAP "150,420"
sleep 1.5
echo "=== 日志 ==="
sudo awk '/### KEYDBG/{f=1;next} f' /var/log/zynq-desktop.log | tail -12