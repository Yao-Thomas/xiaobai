#!/bin/bash
echo "=== 语法检查 ==="
cd /home/zynq/ui
for f in fbui.py desktop.py apps_mines.py apps_calc.py apps_draw.py apps_files.py apps_term.py apps_sys.py apps_net.py apps_about.py; do
  if python3 -m py_compile "$f" 2>/tmp/err.txt; then
    echo "  OK    $f"
  else
    echo "  错误  $f"
    head -4 /tmp/err.txt
  fi
done
echo ""
echo "=== 重启桌面 ==="
pkill -9 -f "[d]esktop.py" 2>/dev/null
sleep 1
rm -f /home/zynq/ui/__pycache__/*.pyc 2>/dev/null
systemctl start zynq-desktop.service
sleep 9
systemctl is-active zynq-desktop.service
echo "=== 日志 ==="
tail -5 /var/log/zynq-desktop.log
echo DONE
