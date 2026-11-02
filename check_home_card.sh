#!/bin/bash
echo "=== home.py 的音乐卡片代码 ==="
sed -n '255,320p' /home/zynq/ui/home.py
echo
echo "=== 状态文件在不在 ==="
ls -l /tmp/zynq_music.json 2>/dev/null && cat /tmp/zynq_music.json
echo
echo "=== 音乐目录 ==="
ls -1 /home/zynq/Music/*.wav 2>/dev/null | wc -l
echo "  （上面是 wav 个数）"