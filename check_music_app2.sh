#!/bin/bash
echo "=== 1) apps_music.py 的播放处理（100-170 行）==="
sed -n '100,170p' /home/zynq/ui/apps_music.py
echo
echo "=== 2) 桌面服务状态 ==="
systemctl is-active zynq-desktop
echo
echo "=== 3) /tmp/zynq_music.json 相关代码 ==="
grep -nE "zynq_music|json.dump|MUSIC_STATE" /home/zynq/ui/apps_music.py /home/zynq/ui/home.py 2>/dev/null | head -15
echo
echo "=== 4) 音乐 App 是怎么被启动的（桌面图标）==="
grep -rnE "apps_music" /home/zynq/ui/*.py /home/zynq/.desktop* 2>/dev/null | head -10