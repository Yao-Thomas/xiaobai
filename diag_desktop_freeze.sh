#!/usr/bin/env bash
echo "=== 1) 桌面服务状态 ==="
systemctl status zynq-desktop --no-pager 2>/dev/null | head -12
echo
echo "=== 2) 桌面日志（最近 40 行）==="
sudo journalctl -u zynq-desktop -n 40 --no-pager 2>/dev/null | tail -30
echo
echo "=== 3) 桌面进程在干嘛（CPU 时间能看出是不是死循环）==="
pid=$(systemctl show -p MainPID --value zynq-desktop)
echo "  PID=$pid"
ps -p $pid -o pid,stat,etime,time,pcpu,pmem,args 2>/dev/null
echo
echo "=== 4) 抓一下 Python 栈（看卡在哪）==="
sudo timeout 8 cat /proc/$pid/task/*/stack 2>/dev/null | head -5
sudo cat /proc/$pid/wchan 2>/dev/null && echo " <- wchan"
echo
echo "=== 5) 音质的 App 文件是否完好 ==="
python3 -c "import ast; ast.parse(open('/home/zynq/ui/apps_music.py').read()); print('  apps_music.py 语法 OK')"
ls -l /home/zynq/ui/apps_music.py*
echo
echo "=== 6) 直接试导入（重现崩溃）==="
cd /home/zynq/ui && sudo python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
import apps_music
print('  导入 OK')
print('  Music 类有 delete 方法:', hasattr(apps_music.Music, 'delete'))
" 2>&1 | tail -12
echo
echo "=== 7) 桌面在画吗（看 framebuffer 时间戳）==="
ls -l /dev/fb0 2>/dev/null
cat /sys/class/graphics/fb0/virtual_size 2>/dev/null
