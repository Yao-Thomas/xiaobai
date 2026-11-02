#!/usr/bin/env bash
echo "=== 播放中读 ES8388 的 DAC 数字音量寄存器（0x1A/0x1B）==="
echo -n "  是否有 aplay 在跑: "
ps aux | grep -c "[a]play"
echo
echo "  寄存器直读（i2cget）:"
for r in 0x1a 0x1b 0x2e 0x2f 0x30 0x31 0x27 0x2a; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
echo
echo "  amixer 视角:"
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 对照：不播放时（先停）==="
curl -s --max-time 8 -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8767/stop >/dev/null 2>&1
sleep 1.5
echo "  寄存器:"
for r in 0x1a 0x1b 0x2e 0x30; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 再启动播放，播放中立刻读 ==="
aplay -q /home/zynq/Music/03_小星星.wav &
sleep 1.0
echo "  播放中的寄存器:"
for r in 0x1a 0x1b 0x2e 0x30; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
wait
echo
echo "=== 播完后 ==="
for r in 0x1a 0x1b; do
  v=$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)
  printf "    0x%s = %s\n" "${r#0x}" "$v"
done
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
