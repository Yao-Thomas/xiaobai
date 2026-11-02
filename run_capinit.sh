cd /home/zynq
echo "=== 初始化前先录一次（对照）==="
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/b4.raw 2>/dev/null
sudo python3 -c "
import array, math
a = array.array('i'); a.frombytes(open('/tmp/b4.raw','rb').read())
for i in range(len(a)):
    if a[i] >= 0x800000: a[i] -= 0x1000000
L = a[0::2]
rms = math.sqrt(sum(float(x)*x for x in L)/len(L))
print('  L RMS = %.1f dBFS  峰值=%d' % (20*math.log10(rms/8388608.0) if rms>0 else -999, max(abs(x) for x in L)))
"
echo
echo "=== 跑初始化 ==="
sudo python3 audio_cap_init.py --test 2>&1