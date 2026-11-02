#!/bin/bash
rm -rf /home/zynq/ui/__pycache__
cd /home/zynq/ui
echo "=== 语法检查 ==="
python3 -c "import py_compile; py_compile.compile('desktop.py', cfile='/tmp/d.pyc', doraise=True); print('  desktop.py OK')"
echo ""
echo "=== 重启桌面 ==="
pkill -9 -f "[d]esktop.py" 2>/dev/null
sleep 1
systemctl start zynq-desktop.service
sleep 11
echo -n "服务状态: "; systemctl is-active zynq-desktop.service
pgrep -af "[d]esktop.py" | head -1
echo ""
echo "=== 日志 ==="
tail -5 /var/log/zynq-desktop.log
echo RESTART_DONE
