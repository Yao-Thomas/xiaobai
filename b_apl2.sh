echo "=== 1) 700-800 行的类结构 ==="
sed -n '700,800p' /home/zynq/ui/audio_pl.py | grep -nE "^class |^    def |^# " 
echo
echo "=== 2) 所有顶层类 ==="
grep -nE "^class " /home/zynq/ui/audio_pl.py
echo
echo "=== 3) 谁在用 audio_pl 录音（找调用者）==="
grep -rln "audio_pl" /home/zynq --include="*.py" 2>/dev/null | head -10
echo
echo "=== 4) read_ring 附近的代码 ==="
sed -n '780,830p' /home/zynq/ui/audio_pl.py