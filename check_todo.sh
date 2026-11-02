echo "=== 1) /selftest 端点还是占位实现吗 ==="
grep -nA3 '"/selftest"' /home/zynq/ui/audio_alsa_svc.py | head -8
echo
echo "=== 2) 声学自测脚本的端点有没有接上 ==="
grep -c "acoustic_selftest" /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 3) 接口约定单里有没有 CNN 地址 ==="
grep -rn "43CD0000\|0x43CD" /home/zynq/ 2>/dev/null | head -3
echo
echo "=== 4) 现在板子上所有自研/新增的脚本 ==="
ls -la /home/zynq/*.py 2>/dev/null | awk '{print "  " $5, $9}' | head -30
echo
echo "=== 5) 演示/申报材料有没有 ==="
ls -la /home/zynq/*演示* /home/zynq/*申报* 2>/dev/null || echo "  (板子上没有)"