#!/bin/sh
# diag_play_conflict.sh —— 查放音不稳定的根因
#
# 诊断结论（前一步）：同一个音量连测 5 次，标准差 16.8 dB，
# 峰值有时 8388607 有时 874 —— 放音时好时坏。
#
# 假设：zynq-audio 服务（也是 ALSA 播放）正占着声卡，和 aplay 冲突。
# 这个脚本对比"服务运行中"vs"服务停掉"两种情况，并抓 aplay 的报错。

echo "======================================================"
echo " 放音冲突诊断"
echo "======================================================"
echo

WAV=/tmp/_conf_tone.wav
python3 - <<'PY'
import array, math, struct
RATE=44100; n=int(1.0*RATE); peak=int(0.6*32767)
buf=array.array('h')
for i in range(n):
    v=int(peak*math.sin(2*math.pi*990.53*i/RATE)); buf.append(v); buf.append(v)
with open('/tmp/_conf_tone.wav','wb') as f:
    d=buf.tobytes()
    f.write(b'RIFF'+struct.pack('<I',36+len(d))+b'WAVE')
    f.write(b'fmt '+struct.pack('<IHHIIHH',16,1,2,RATE,RATE*4,4,16))
    f.write(b'data'+struct.pack('<I',len(d))); f.write(d)
print("  测试音已生成")
PY
echo

play_once() {
  # 放一次并抓返回码/报错
  OUT=$(aplay -q -D default "$WAV" 2>&1)
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "     ★ aplay 退出码=$RC  $OUT" | head -2
  fi
  return $RC
}

measure() {
  # 放一次 + 录一次，报峰值
  amixer -q -c 0 sset Playback 140 2>/dev/null
  arecord -q -D hw:0,1 -f S24_LE -c 2 -r 44100 -d 1 -t raw /tmp/_b.raw 2>/dev/null
  aplay -q -D default "$WAV" 2>/dev/null &
  AP=$!
  sleep 0.2
  arecord -q -D hw:0,1 -f S24_LE -c 2 -r 44100 -d 1 -t raw /tmp/_p.raw 2>/dev/null
  wait $AP 2>/dev/null
  python3 -c "
import array, math
def peak(p):
    a=array.array('i'); a.frombytes(open(p,'rb').read())
    for i in range(len(a)):
        if a[i]>=0x800000: a[i]-=0x1000000
    L=a[0::2]
    return max(abs(x) for x in L) if L else 0
print('    %d' % peak('/tmp/_p.raw'))
"
}

echo "【A】zynq-audio 服务【运行中】—— 连测 6 次"
echo "  服务状态: $(systemctl is-active zynq-audio)"
echo "  峰值:"
i=1
while [ $i -le 6 ]; do
  printf "    #%d " $i
  measure
  i=$((i+1))
done
echo
echo "  顺便看 aplay 直接跑的返回码（5 次）:"
i=1
while [ $i -le 5 ]; do
  printf "    #%d " $i
  if play_once; then echo "    退出码=0"; fi
  i=$((i+1))
done
echo

echo "【B】停掉 zynq-audio —— 再连测 6 次"
sudo systemctl stop zynq-audio
sleep 3
echo "  服务状态: $(systemctl is-active zynq-audio)"
echo "  峰值:"
i=1
while [ $i -le 6 ]; do
  printf "    #%d " $i
  measure
  i=$((i+1))
done
echo
echo "  aplay 返回码（5 次）:"
i=1
while [ $i -le 5 ]; do
  printf "    #%d " $i
  if play_once; then echo "    退出码=0"; fi
  i=$((i+1))
done
echo

echo "【C】看谁占着声卡"
sudo fuser -v /dev/snd/* 2>&1 | head -20
echo
echo "  打开的音频设备:"
sudo lsof /dev/snd/* 2>/dev/null | head -10 || echo "    (lsof 没有)"
echo

echo "【D】恢复服务"
sudo systemctl start zynq-audio
sleep 4
echo "  zynq-audio: $(systemctl is-active zynq-audio)"
echo
echo "======================================================"
echo " 判读"
echo "======================================================"
echo "  A 组不稳 + B 组稳  → ★ 就是服务占用冲突（改：自测时先停服务）"
echo "  A/B 都不稳          → 是驱动/DMA 层的问题（再看 aplay 报错）"
echo "  A/B 都稳            → 之前的波动是偶发"
echo "======================================================"
