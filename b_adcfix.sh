cd /home/zynq
echo "=== 验证符号扩展解析 ==="
sudo python3 analyze_wav.py /tmp/cap44.wav 2>&1 | head -20
echo
echo "=== ★ 跑 ADC 输入选择实验（cap_adc_fix.py）==="
sudo python3 ui/cap_adc_fix.py 2>&1 | tail -35