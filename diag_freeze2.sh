#!/usr/bin/env bash
echo "=== 1) 桌面完整日志里有没有 Python 异常 ==="
sudo journalctl -u zynq-desktop --since "25 min ago" --no-pager 2>/dev/null |
  grep -iE "Traceback|Error|Exception|File \"|line [0-9]+|music" | tail -25
echo
echo "=== 2) 有没有 [music] 开头的输出（说明 App 被打开过）==="
sudo journalctl -u zynq-desktop --since "25 min ago" --no-pager 2>/dev/null | grep -i "music" | tail -8
echo
echo "=== 3) 桌面主进程的线程在干嘛 ==="
pid=$(systemctl show -p MainPID --value zynq-desktop)
echo "  PID=$pid  线程数=$(ls /proc/$pid/task 2>/dev/null | wc -l)"
for t in $(ls /proc/$pid/task 2>/dev/null | head -8); do
  echo "    线程 $t: $(cat /proc/$pid/task/$t/comm 2>/dev/null)  wchan=$(cat /proc/$pid/task/$t/wchan 2>/dev/null)"
done
echo
echo "=== 4) 重启桌面，看能不能恢复 ==="
sudo systemctl restart zynq-desktop
sleep 12
echo -n "  is-active: "; systemctl is-active zynq-desktop
echo "  重启后的日志尾部:"
sudo journalctl -u zynq-desktop -n 6 --no-pager 2>/dev/null | tail -4
echo
echo "=== 5) 跑两次截图看时钟有没有跳（用修好的 shot_fb）==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/a.raw 2>&1
md5sum /tmp/a.raw
sleep 3
sudo python3 /home/zynq/ui/shot_fb.py /tmp/b.raw 2>&1
md5sum /tmp/b.raw
echo
if [ "$(md5sum /tmp/a.raw | cut -d' ' -f1)" = "$(md5sum /tmp/b.raw | cut -d' ' -f1)" ]; then
  echo "  ✗ 3 秒后画面完全相同 -> 还是冻的"
else
  echo "  ✓ 画面在变 -> 桌面复原了"
fi
