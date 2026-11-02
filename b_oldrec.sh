cd /home/zynq
echo "=== 1) 以前的录音文件（这是关键判据）==="
ls -la /home/zynq/Music/*.wav 2>/dev/null | head -12
echo
echo "=== 2) 逐个分析音量 ==="
for f in /home/zynq/Music/*.wav; do
  [ -f "$f" ] || continue
  printf "  %-34s " "$(basename $f)"
  sudo python3 analyze_wav.py "$f" 2>/dev/null | grep -E "声道 0|RMS=" | head -2 | tr '\n' ' '
  echo
done
echo
echo "=== 3) I2C 总线扫描找 ES8388 ==="
for b in 0 1 2; do
  echo "  --- i2c-$b ---"
  sudo i2cdetect -y $b 2>&1 | head -6
done