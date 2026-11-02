#!/bin/bash
# 1) 扫所有混音器控件找残余增益  2) 把 WAV 软件放大到接近满量程
echo "=== 1) 所有控件当前值（找没拉满的增益）==="
for c in $(amixer -c 0 scontrols 2>/dev/null | sed "s/^Simple mixer control '//;s/'.*//"); do
  line=$(amixer -c 0 sget "$c" 2>/dev/null | grep -E "Front Left|Mono:" | head -1)
  case "$line" in
    *dB*) printf "  %-30s %s\n" "$c" "$(echo $line | sed 's/.*Playback //;s/.*Capture //')" ;;
  esac
done
echo
echo "=== 2) 把《小星星》软件放大到 -0.5 dBFS ==="
python3 - <<'PY'
import wave, struct, os, math
src = "/home/zynq/Music/03_小星星.wav"
dst = "/tmp/星星_放大.wav"
w = wave.open(src, "rb")
ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
pk = max(abs(x) for x in v)
target = int(0.945 * 32767)          # -0.5 dBFS
g = target / float(pk)
print("  原峰值=%d (%.1f dBFS)  放大 %.2f 倍 (%+.1f dB)"
      % (pk, 20*math.log10(pk/32767.0), g, 20*math.log10(g)))
# 软限幅，避免削顶产生刺耳谐波
out = []
for x in v:
    y = math.tanh(x * g / 32767.0 * 1.05) / math.tanh(1.05)
    out.append(max(-32768, min(32767, int(y * 32767))))
data = struct.pack("<%dh" % len(out), *out)
w = wave.open(dst, "wb")
w.setnchannels(ch); w.setsampwidth(sw); w.setframerate(r)
w.writeframes(data); w.close()
print("  已写 %s  %d 字节" % (dst, os.path.getsize(dst)))
npk = max(abs(x) for x in out)
print("  新峰值=%d (%.1f dBFS)" % (npk, 20*math.log10(npk/32767.0)))
PY
echo
echo "=== 3) 播放放大版 ==="
aplay -q /tmp/星星_放大.wav
echo "  aplay 退出码: $?"
