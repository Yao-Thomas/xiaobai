grep -rn "restart zynq-desktop\|systemctl restart\|os.execv\|sys.exit" /home/zynq/ui/*.py 2>/dev/null | head -12 | sed 's/^/  /'
echo
echo "=== 各 App 的退出方式 ==="
grep -rn "def run" /home/zynq/ui/apps_term.py 2>/dev/null | head -3 | sed 's/^/  /'