echo "=== 1) WiFi 应用在 APPS 里的注册 ==="
grep -nE "apps_wifi|WiFi|wifi" /home/zynq/ui/desktop.py | head -10
echo
echo "=== 2) 设置应用里有没有入口 ==="
grep -nE "apps_wifi|WiFi|wifi" /home/zynq/ui/apps_settings.py | head -10
echo
echo "=== 3) 有没有别的入口（比如 apps_net）==="
grep -nE "apps_wifi" /home/zynq/ui/*.py | head -10