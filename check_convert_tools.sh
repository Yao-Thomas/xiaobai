echo "=== 板上可用的音频转换工具 ==="
for t in sox ffmpeg avconv; do
  p=$(command -v $t 2>/dev/null)
  [ -n "$p" ] && echo "  ✓ $t -> $p" || echo "  ✗ $t"
done
echo
echo "=== python 有没有 numpy/scipy ==="
python3 -c "import numpy; print('  ✓ numpy', numpy.__version__)" 2>/dev/null || echo "  ✗ numpy"
python3 -c "import scipy; print('  ✓ scipy', scipy.__version__)" 2>/dev/null || echo "  ✗ scipy"
echo
echo "=== 硬件到底接受什么格式（试几个）==="
for spec in "S16_LE 44100 2" "S16_LE 16000 1" "S24_LE 44100 2" "S16_LE 48000 2"; do
  set -- $spec
  printf "  %-8s %-6s %-2s ch: " "$1" "$2" "$3"
  arecord -q -D hw:0,0 -f $1 -r $2 -c $3 -d 1 /tmp/_f.wav 2>/dev/null && echo "录音OK" || echo "录音不行"
done
echo
echo "=== 播放侧试几个格式（走 default）==="
python3 - <<'PY'
import wave, struct, math, subprocess, os
for (rate, ch, name) in [(44100,2,'44k2ch'), (16000,1,'16k1ch'), (48000,2,'48k2ch'), (22050,1,'22k1ch')]:
    p = '/tmp/_t_%s.wav' % name
    w = wave.open(p,'wb'); w.setnchannels(ch); w.setsampwidth(2); w.setframerate(rate)
    fr = bytearray()
    for i in range(int(rate*0.4)):
        s = int(8000*math.sin(2*math.pi*440*i/rate))
        for _ in range(ch): fr += struct.pack('<h', s)
    w.writeframes(fr); w.close()
    r = subprocess.run(['aplay','-q',p], capture_output=True)
    print('  %-8s %-6d %dch -> 退出码 %d %s' % (name, rate, ch, r.returncode,
          (r.stderr.decode(errors='replace').strip().split('\n')[0][:70] if r.returncode else 'OK')))
PY