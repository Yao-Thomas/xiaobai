try_rec() {
  desc="$1"; shift
  rm -f /tmp/t.wav
  out=$(sudo arecord "$@" -d 2 /tmp/t.wav 2>&1)
  rc=$?
  if [ $rc -eq 0 ] && [ -s /tmp/t.wav ]; then
    sz=$(stat -c%s /tmp/t.wav)
    printf "  ✓ %-52s %d 字节\n" "$desc" "$sz"
  else
    printf "  ✗ %-52s rc=%d  %s\n" "$desc" "$rc" "$(echo "$out" | grep -oE 'set_params[^:]*: [^\n]*' | head -1)"
  fi
}

echo "=== 各种采集配置试验 ==="
try_rec "hw:0,1 默认"                    -D hw:0,1 -f S24_LE -r 48000 -c 2
try_rec "hw:0,1 period=1024 periods=4"   -D hw:0,1 -f S24_LE -r 48000 -c 2 --period-size=1024 --periods=4
try_rec "hw:0,1 period=512 periods=2"    -D hw:0,1 -f S24_LE -r 48000 -c 2 --period-size=512 --periods=2
try_rec "hw:0,1 r=44100"                 -D hw:0,1 -f S24_LE -r 44100 -c 2
try_rec "plughw:0,1 48000"               -D plughw:0,1 -f S24_LE -r 48000 -c 2
try_rec "plughw:0,1 S16 48000"           -D plughw:0,1 -f S16_LE -r 48000 -c 2
try_rec "hw:0,1 96000"                   -D hw:0,1 -f S24_LE -r 96000 -c 2 --period-size=2048 --periods=3