#!/usr/bin/env bash
echo "=== 1) 播放前状态 ==="
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
printf "  0x1D = %s\n" "$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "############################################################"
echo "#  ★ 播放《半岛铁盒》周杰伦  5 分 19 秒"
echo "#     文件: /home/zynq/Music/02_半岛铁盒.wav (53.7 MB)"
echo "#     RMS -12.0 dBFS  峰值 -1.6 dBFS"
echo "############################################################"
# 后台触发播放（/play 会阻塞到播完，所以放后台）
(setsid nohup curl -s --max-time 400 -X POST \
   -H 'Content-Type: application/json' \
   -d '{"file":"/home/zynq/Music/02_半岛铁盒.wav"}' \
   http://127.0.0.1:8767/play > /tmp/bandao_play.log 2>&1 &)
sleep 4
echo
echo "=== 2) 确认在播 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 3) aplay 进程 ==="
ps aux | grep "[a]play" | head -2
echo
echo "=== 4) 播放中寄存器（确认没被改小）==="
printf "  "
for r in 0x1a 0x1b 0x2e 0x30; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
