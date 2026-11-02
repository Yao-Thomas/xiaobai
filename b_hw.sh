echo "=== 1) 谁占着声卡 ==="
sudo ls -la /proc/*/fd 2>/dev/null | grep -c "snd" || true
for p in $(ls /proc | grep -E "^[0-9]+$"); do
  if sudo ls -la /proc/$p/fd 2>/dev/null | grep -q "/dev/snd"; then
    echo "  PID $p: $(cat /proc/$p/comm 2>/dev/null)"
    sudo ls -la /proc/$p/fd 2>/dev/null | grep "/dev/snd" | sed 's/^/      /'
  fi
done
echo
echo "=== 2) 硬件支持的参数 ==="
sudo arecord -D hw:0,1 --dump-hw-params /dev/null 2>&1 | head -25