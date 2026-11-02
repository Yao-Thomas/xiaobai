cd /home/zynq
echo "=== 以前的录音文件 ==="
ls -la /home/zynq/Music/*.wav 2>/dev/null | head -12
echo
echo "=== 逐个分析（只取前几行）==="
for f in /home/zynq/Music/*.wav; do
  [ -f "$f" ] || continue
  echo "--- $(basename $f) ---"
  sudo python3 /home/zynq/analyze_wav.py "$f" 2>/dev/null | grep -E "声道=|声道 [01]:|RMS=|恒定|极低|正常|满量程" | head -8
done