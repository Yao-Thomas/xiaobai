cd /home/zynq
echo "=== 1) audio_alsa_svc.py 里 /record 的实现 ==="
grep -nE "record|arecord" /home/zynq/ui/audio_alsa_svc.py | head -15
echo
echo "=== 2) 看录到的原始样本（16bit 单声道）==="
sudo python3 - <<'PYEOF'
import struct, array
d = open("/tmp/api_rec.wav","rb").read()
i = d.find(b"data")
hdr = i+8
afmt,nch,rate,brate,balign,bits = struct.unpack_from("<HHIIHH", d, 20)
print("  格式: %dHz %dch %dbit" % (rate,nch,bits))
n = (len(d)-hdr)//balign
a = array.array("h"); a.frombytes(d[hdr:hdr+n*nch*2])
print("  总样本 %d" % len(a))
print("  前 64 个: %s" % list(a[:64]))
import collections
cnt = collections.Counter(a)
print("  出现最多的 10 个值:")
for v,c in cnt.most_common(10):
    print("     %6d : %d 次" % (v,c))
print("  不同值总数: %d" % len(cnt))
# 相邻差
diffs = [a[i+1]-a[i] for i in range(min(len(a)-1, 2000))]
print("  前 2000 个相邻差的范围: %d .. %d" % (min(diffs), max(diffs)))
PYEOF
echo
echo "=== 3) 跑完 PL 工具后，ALSA 采集是不是又变成静音了？==="
sudo rm -f /tmp/chk.wav
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 /tmp/chk.wav 2>&1 | head -2
sudo python3 /home/zynq/analyze_wav.py /tmp/chk.wav 2>&1 | grep -E "声道 0|RMS=|恒定|极低|满量程" | head -4