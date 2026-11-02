echo "=== 1) 采集相关控件的当前值 ==="
for n in "Capture Digital Volume" "Capture Mute" "Capture Polarity" \
         "Left Channel Capture Volume" "Right Channel Capture Volume" \
         "ALC Capture Function" "ALC Capture Target Volume" "ALC Capture Max PGA" \
         "ALC Capture Min PGA" "ALC Capture NG Switch" "Output 1 Playback Volume" \
         "Output 2 Playback Volume" "Playback Volume"; do
  v=$(sudo amixer -c 0 sget "$n" 2>/dev/null | grep -E "^\s*(Front|Mono|Limits|:)" | tr '\n' ' ')
  printf "  %-30s %s\n" "$n" "$(echo $v | sed 's/  */ /g')"
done
echo
echo "=== 2) 录 3 秒（16-bit / 48k / 立体声）==="
sudo arecord -D hw:0,1 -f S16_LE -r 48000 -c 2 -d 3 /tmp/cap_test.wav 2>&1 | tail -3
ls -la /tmp/cap_test.wav
echo
echo "=== 3) 分析波形 ==="
sudo python3 - <<'PYEOF'
import wave, struct, math
w = wave.open("/tmp/cap_test.wav")
n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
print("  格式: %d 声道 / %d bit / %d Hz / %d 帧 (%.2f 秒)" % (ch, sw*8, sr, n, n/sr))
data = w.readframes(n)
if sw == 2:
    s = struct.unpack("<%dh" % (n*ch), data)
else:
    s = struct.unpack("<%db" % (n*ch), data)
for c in range(ch):
    xs = s[c::ch]
    mx, mn = max(xs), min(xs)
    rms = math.sqrt(sum(float(x)*x for x in xs)/len(xs))
    dbfs = 20*math.log10(rms/32768.0) if rms > 0 else -999
    nz = sum(1 for x in xs if x != 0)
    const = sum(1 for x in xs if x in (mx,))
    print("  声道%d: min=%-7d max=%-7d 峰峰=%-7d RMS=%.1f (%.1f dBFS) 非零=%d/%d" %
          (c, mn, mx, mx-mn, rms, dbfs, nz, len(xs)))
    # 前 20 个样本看看
    print("        前20样本: %s" % xs[:20])
    # 是否恒定不变
    if mx == mn:
        print("        ★★★ 这一路是【恒定值】%d —— 完全没信号" % mx)
PYEOF