cd /home/zynq
echo "=== 温度 / DAC 寄存器 ==="
echo -n "  温度: "; sudo python3 thermal_guard.py --once
echo "  --- ES8388 DAC 相关 ---"
sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
def rd(r):
    os.write(fd, bytes([r])); return os.read(fd,1)[0]
for r,n in [(0x02,'电源'),(0x04,'DAC电源'),(0x08,'主模式'),(0x0B,'DAC Ctrl1'),
            (0x0C,'DAC Ctrl2'),(0x10,'DAC Ctrl3'),(0x17,'DAC Ctrl4'),
            (0x18,'DAC Ctrl5'),(0x19,'DAC音量L'),(0x1A,'DAC音量R'),
            (0x1B,'DAC Ctrl10'),(0x1D,'DAC Ctrl8 Vpp'),(0x1E,'DAC Ctrl9'),
            (0x26,'DAC Ctrl16'),(0x27,'DAC Ctrl17'),
            (0x2E,'Output1L'),(0x2F,'Output1R'),(0x30,'Output2L'),(0x31,'Output2R')]:
    print('    0x%02X %-14s = 0x%02X' % (r, n, rd(r)))
os.close(fd)
"
echo
echo "=== 播放音量（amixer）==="
amixer -c 0 sget Playback 2>/dev/null | grep -E "Front|Limits"
amixer -c 0 sget "Output 1" 2>/dev/null | grep -E "Front|Limits"
amixer -c 0 sget "Output 2" 2>/dev/null | grep -E "Front|Limits"
echo
echo "=== aplay 能不能成功放一个音 ==="
sudo python3 -c "
import array, math, struct, subprocess
RATE=44100; n=int(1.0*RATE); peak=int(0.9*32767)
buf=array.array('h')
for i in range(n):
    v=int(peak*math.sin(2*math.pi*1000*i/RATE)); buf.append(v); buf.append(v)
with open('/tmp/_t.wav','wb') as f:
    d=buf.tobytes()
    f.write(b'RIFF'+struct.pack('<I',36+len(d))+b'WAVE')
    f.write(b'fmt '+struct.pack('<IHHIIHH',16,1,2,RATE,RATE*4,4,16))
    f.write(b'data'+struct.pack('<I',len(d))); f.write(d)
p = subprocess.run(['aplay','-D','hw:0,0','/tmp/_t.wav'], capture_output=True)
print('  aplay 退出码 =', p.returncode)
if p.stderr: print('  stderr:', p.stderr.decode()[:200])
"
echo
echo "=== 最大音量下再测频谱 ==="
sudo python3 audio_spectrum.py --secs 2.5 --play 990 --vol 190 --top 6 2>&1 | tail -18