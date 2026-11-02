cd /home/zynq/ui
TS=$(date +%Y%m%d_%H%M%S)
sudo cp apps_settings.py apps_settings.py.bak_sigfix_$TS
echo "  已备份: apps_settings.py.bak_sigfix_$TS"
sudo cp /tmp/apps_settings_new.py apps_settings.py
sudo chown zynq:zynq apps_settings.py
md5sum apps_settings.py
python3 -c "import ast,io; ast.parse(io.open('apps_settings.py',encoding='utf-8').read()); print('syntax OK')"
echo
echo "=== 验证修复：动态探测网卡 + 读信号 ==="
python3 - <<'PYEOF'
import os, subprocess
w = ""
for n in sorted(os.listdir("/sys/class/net")):
    if n.startswith("wl"):
        w = n; break
print("  探测到网卡:", w)
out = subprocess.run("iwconfig %s 2>/dev/null | grep -o 'Signal level=[^ ]*'" % w,
                     shell=True, stdout=subprocess.PIPE).stdout.decode().strip()
print("  信号强度   :", out or "(空)")
PYEOF
echo
echo "=== 旧命令（硬编码 wlan0）对比 ==="
iwconfig wlan0 2>/dev/null | grep -o 'Signal level=[^ ]*' || echo "  (空 - 这就是 bug)"