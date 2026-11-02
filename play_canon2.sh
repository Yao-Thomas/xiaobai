#!/usr/bin/env bash
echo "=== 确认文件在（用 ASCII 名字，排除中文名干扰）==="
ls -l /home/zynq/Music/05_canon.wav 2>/dev/null || cp "/home/zynq/Music/05_卡农.wav" /home/zynq/Music/05_canon.wav
ls -l /home/zynq/Music/05_canon.wav
echo
echo "=== 增益确认 ==="
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
echo
echo "############################################################"
echo "#  ★ 播放《卡农》16 秒（RMS -10.1 dBFS，多声部编曲）"
echo "#     走服务接口（和音乐 App 同一条路径）"
echo "############################################################"
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/05_canon.wav"}' \
  http://127.0.0.1:8767/play
echo
echo "  --- 放完 ---"
echo
echo "=== 状态 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
