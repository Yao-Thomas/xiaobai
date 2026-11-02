#!/bin/bash
echo "=== 现在的混音器实际值（是不是被服务改回去了）==="
for c in 'Playback' 'Output 1' 'Output 2' 'Capture Digital'; do
  printf "  %-18s " "$c"
  amixer -c 0 sget "$c" 2>/dev/null | grep -E "Front Left|Mono:" | head -1 | sed 's/^ *//'
done
echo
echo "=== audio_alsa_svc.py 的 set_volume 改哪些控件 ==="
sed -n '40,90p' /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 服务启动时的默认音量 ==="
grep -nE "volume|amixer|192|33|27" /home/zynq/ui/audio_alsa_svc.py | head -20