ls -l "/home/zynq/Music/02_半岛铁盒.wav" | awk '{printf "  %d 字节 (%.1f MB)\n", $5, $5/1048576}'
python3 - <<'PY'
import wave, struct, math
p = "/home/zynq/Music/02_半岛铁盒.wav"
w = wave.open(p, "rb")
ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
pk = max(abs(x) for x in v)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
print("  %dHz %dch %dbit  %.1f 秒 (%.1f 分钟)" % (r, ch, sw*8, n/float(r), n/float(r)/60))
print("  RMS %.1f dBFS   峰值 %.1f dBFS" % (
    20*math.log10(max(1e-9,rms/32767.0)), 20*math.log10(max(1e-9,pk/32767.0))))
print("  ★ 格式是硬件原生支持的 44100/2ch/16bit -> 播放无需转换")
PY
echo
echo "=== 音乐目录 ==="
ls -l /home/zynq/Music/*.wav | awk '{printf "  %8.1f MB  %s\n", $5/1048576, $9}'
echo
echo "=== 磁盘 ==="
df -h / | tail -1 | awk '{print "  已用 "$3"  剩余 "$4"  使用率 "$5}'