#!/usr/bin/env bash
echo "=== 重启后音量是否自动恢复（验证我写的 ExecStartPre）==="
echo "  服务音量:"
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "  实际混音器:"
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left"
echo
echo "=== ES8388 寄存器直读（不播放时）==="
for r in 0x1a 0x1b 0x2e 0x2f 0x30 0x31; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "  0x%s = %s\n" "${r#0x}" "$v"
done
echo
echo "=== 现在放一次，播放中立刻读寄存器（看驱动会不会把音量改小）==="
aplay -q /home/zynq/Music/03_小星星.wav &
AP=$!
sleep 1.2
echo "  播放中:"
for r in 0x1a 0x1b 0x2e 0x30; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
sleep 2.5
echo "  播放 3.7 秒后:"
for r in 0x1a 0x1b 0x2e 0x30; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
wait $AP 2>/dev/null
echo "  aplay 退出码: $?"
echo
echo "=== 播完后 ==="
for r in 0x1a 0x1b 0x2e 0x30; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "  0x%s = %s\n" "${r#0x}" "$v"
done
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
