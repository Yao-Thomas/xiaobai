echo "=== 1) arecord 是什么 ==="
which arecord
file $(which arecord) 2>/dev/null
ls -la $(which arecord)
echo
echo "=== 2) 如果是脚本，看内容 ==="
for p in /usr/bin/arecord /usr/local/bin/arecord /bin/arecord; do
  if [ -f $p ]; then
    echo "--- $p ---"
    head -3 $p | cat -v | head -3
  fi
done
echo
echo "=== 3) 找 BUFFER_BYTES 这个字符串是谁打的 ==="
sudo grep -rl "BUFFER_BYTES" /home/zynq /usr/local/bin /usr/bin 2>/dev/null | head -5
echo
echo "=== 4) 录音相关的工具 ==="
ls -la /home/zynq/*.py /home/zynq/ui/*.py 2>/dev/null | grep -iE "rec|cap|audio" | head -10
ls -la /usr/local/bin/ 2>/dev/null | head -20
echo
echo "=== 5) 音频服务在不在占用设备 ==="
sudo fuser -v /dev/snd/* 2>&1 | head -12
echo
echo "=== 6) 系统里有哪些录音程序 ==="
for c in arecord parec ecasound rec sox; do printf "  %-10s %s\n" "$c" "$(which $c 2>/dev/null || echo -)"; done