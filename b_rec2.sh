echo "=== 1) arecord 完整输出 + 退出码 ==="
sudo arecord -D hw:0,1 -f S24_LE -r 48000 -c 2 -d 3 /tmp/cap24.wav > /tmp/arec.out 2>&1
echo "  退出码=$?"
echo "  --- 输出 ---"
cat /tmp/arec.out | head -10
echo "  --- 文件 ---"
ls -la /tmp/cap24.wav 2>/dev/null || echo "  ★ 没生成文件"
echo
echo "=== 2) cap_adc_fix.py（之前的尝试）==="
cat /home/zynq/ui/cap_adc_fix.py