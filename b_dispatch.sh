echo "=== 1) 桌面里打开浏览器应用的方式 ==="
grep -nE "def run_app|self\.app|\.tap\(|app\.tap|def _do_tap" /home/zynq/ui/desktop.py | head -20
echo
echo "=== 2) run_app 的实现（怎么进应用的循环）==="
sed -n '/def run_app/,/^    def /p' /home/zynq/ui/desktop.py | head -40
echo
echo "=== 3) 浏览器应用怎么收事件（有没有自己读 touch）==="
grep -nE "def run|touch\.poll|def tap|def on_tap|while True" /home/zynq/ui/apps_browser.py | head -15