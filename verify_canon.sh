#!/usr/bin/env bash
echo "=== 1) 文件信息 ==="
ls -l "/home/zynq/Music/01_卡农_帕赫贝尔.wav" | awk '{printf "  %d 字节  (%.1f MB)\n", $5, $5/1048576}'
echo
echo "=== 2) WAV 头与响度 ==="
python3 - <<'PY'
import wave, struct, math
p = "/home/zynq/Music/01_卡农_帕赫贝尔.wav"
w = wave.open(p, "rb")
ch, sw, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
raw = w.readframes(n); w.close()
v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
pk = max(abs(x) for x in v)
rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
print("  %dHz  %dch  %dbit  %.1f 秒 (%.1f 分钟)" % (r, ch, sw*8, n/float(r), n/float(r)/60))
print("  RMS %.1f dBFS   峰值 %.1f dBFS" % (
    20*math.log10(max(1e-9,rms/32767.0)), 20*math.log10(max(1e-9,pk/32767.0))))
print("  ★ 格式正好是硬件原生支持的 44100/2ch/16bit -> 播放时无需转换")
PY
echo
echo "=== 3) 音乐目录现状 ==="
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{printf "  %8.1f MB  %s\n", $5/1048576, $9}'
echo
echo "=== 4) 磁盘 ==="
df -h / | tail -1 | awk '{print "  已用 "$3"  剩余 "$4"  使用率 "$5}'
echo
echo "=== 5) 时间对齐确认 ==="
date '+  板子: %Y-%m-%d %H:%M:%S %Z (%z)'
echo
echo "=== 6) 音频服务状态（0x1D Vpp 也一起看）==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
printf "  0x1D = "; sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 7) 用官方注入刷新音乐 App 界面，让它扫到新文件 ==="
echo "324,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 3
sudo tail -3 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
