#!/bin/bash
echo "=== 1) apps_music 能不能干净导入 ==="
cd /home/zynq/ui || exit 1
python3 -c "
import sys
sys.path.insert(0, '/home/zynq/ui')
try:
    import apps_music
    print('  OK: 导入成功')
    print('  MUSIC_DIR =', apps_music.MUSIC_DIR)
    print('  AUDIO_URL =', apps_music.AUDIO_URL)
    f = apps_music.scan()
    print('  scan() 找到 %d 个文件' % len(f))
    for x in f[:5]:
        print('    ', x[0], x[2], '字节', '%.2f秒' % x[3])
except Exception as e:
    import traceback; traceback.print_exc()
"
echo
echo "=== 2) 桌面服务最近的报错 ==="
sudo journalctl -u zynq-desktop -n 120 --no-pager 2>/dev/null | grep -iE "error|traceback|exception|music|播放|错误" | tail -20
echo
echo "=== 3) 桌面进程在不在 ==="
ps aux | grep -E "desktop.py" | grep -v grep | head -3 | awk '{print "  PID "$2"  "$11" "$12" "$13}'
echo
echo "=== 4) 触屏注入通道还在吗 ==="
ls -l /tmp/ui_tap 2>/dev/null || echo "  /tmp/ui_tap 不存在（桌面重启后会重建）"
grep -n "ui_tap" /home/zynq/ui/desktop.py 2>/dev/null | head -5
echo
echo "=== 5) 桌面服务定义 ==="
systemctl cat zynq-desktop 2>/dev/null | grep -E "ExecStart|WorkingDirectory|Restart"
