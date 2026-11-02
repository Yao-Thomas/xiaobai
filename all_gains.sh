#!/bin/bash
echo "=== 所有混音器控件 + 当前值（找没拉满的增益）==="
amixer -c 0 scontrols 2>/dev/null | sed "s/^Simple mixer control '//;s/'.*//" | while read c; do
  out=$(amixer -c 0 sget "$c" 2>/dev/null)
  vals=$(echo "$out" | grep -E "Front Left:|Mono:" | head -1 | sed 's/^ *//')
  lim=$(echo "$out" | grep -E "^ *Limits:" | head -1 | sed 's/^ *//')
  printf "  %-28s %-40s %s\n" "$c" "$vals" "$lim"
done
echo
echo "=== 把所有可能的增益都设到最大 ==="
for c in 'Playback' 'Output 1' 'Output 2' 'Left Mixer Left Bypass' 'Right Mixer Right Bypass' 'Left Channel' 'Right Channel' 'Capture Digital'; do
  amixer -c 0 sget "$c" >/dev/null 2>&1 || continue
  case "$c" in
    'Left Mixer Left Bypass'|'Right Mixer Right Bypass') continue ;;   # 这些是开关不是增益
    *) amixer -c 0 -q sset "$c" 100% 2>/dev/null && echo "  $c -> 100%" ;;
  esac
done
echo
echo "=== 最终值 ==="
for c in 'Playback' 'Output 1' 'Output 2'; do
  printf "  %-12s " "$c"
  amixer -c 0 sget "$c" 2>/dev/null | grep -E "Front Left" | head -1 | sed 's/^ *//'
done
echo
echo "=== 通过服务 API 把服务内部音量也同步成 33 ==="
curl -s --max-time 10 -X POST -H 'Content-Type: application/json' \
  -d '{"v":33}' http://127.0.0.1:8767/volume; echo
curl -s --max-time 10 http://127.0.0.1:8767/state; echo
