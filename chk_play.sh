echo "=== 1) 音频服务用的设备 ==="
grep -nE "^CARD|AREAD|PLAY|hw:|plughw|aplay|arecord" /home/zynq/ui/audio_alsa_svc.py | head -20
echo
echo "=== 2) 设备列表 ==="
aplay -l 2>&1 | head -6
arecord -l 2>&1 | head -6
echo
echo "=== 3) 播放设备支持的格式 ==="
sudo aplay -D hw:0,0 --dump-hw-params /dev/null 2>&1 | head -14
echo
echo "=== 4) plughw 能不能自动转换 ==="
sudo python3 -c "
import array, math, struct, subprocess
RATE=44100; n=int(0.5*RATE); peak=int(0.5*32767)
buf=array.array('h')
for i in range(n):
    v=int(peak*math.sin(2*math.pi*1000*i/RATE)); buf.append(v); buf.append(v)
with open('/tmp/_t2.wav','wb') as f:
    d=buf.tobytes()
    f.write(b'RIFF'+struct.pack('<I',36+len(d))+b'WAVE')
    f.write(b'fmt '+struct.pack('<IHHIIHH',16,1,2,RATE,RATE*4,4,16))
    f.write(b'data'+struct.pack('<I',len(d))); f.write(d)
for dev in ('hw:0,0','plughw:0,0','default'):
    p = subprocess.run(['aplay','-q','-D',dev,'/tmp/_t2.wav'], capture_output=True, timeout=20)
    print('  %-12s 退出码=%d  %s' % (dev, p.returncode, p.stderr.decode()[:80].replace(chr(10),' ')))
"