LOG=/var/log/zynq-desktop.log
echo "=== 1) 重启桌面 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  desktop: "; systemctl is-active zynq-desktop
echo -n "  audio:   "; systemctl is-active zynq-audio
sudo truncate -s 0 $LOG 2>/dev/null
echo "  （日志已清空，后面的都是新的）"
echo
echo "=== 2) 增益确认（重启后 drop-in 是否生效）==="
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
printf "  0x1D (Vpp) = "; sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null
echo
echo "=== 3) 音频服务 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 4) 时间 ==="
date '+  %Y-%m-%d %H:%M:%S %Z (%z)'
echo
echo "=== 5) 时钟 App 能不能导入（在真实环境下）==="
cd /home/zynq/ui && sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
import apps_clock
print('  apps_clock 导入 OK, 表盘:', apps_clock.FACES)
" 2>&1 | tail -3
echo
echo "=== 6) 桌面启动日志 ==="
sudo tail -6 $LOG | sed 's/^/  /'