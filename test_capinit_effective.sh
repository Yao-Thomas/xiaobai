#!/bin/sh
# test_capinit_effective.sh —— 决定性实验：我的初始化到底有没有用
#
# 问题：现在采集是好的（-75 dBFS），但 ES8388 的寄存器值本来就是对的
#       （rec_big.py 留下的）。所以分不清是我的初始化起了作用，
#       还是它只是复述了已有状态。
#
# 做法（不用重启，快）：
#   1. 故意把 ES8388 弄回驱动默认值（0x0A=0x50 LINE 输入、0x03=0xF9）
#   2. 录一次 —— 应该是静音（-137）
#   3. 跑我的 audio_cap_init.py
#   4. 再录一次 —— 如果有信号，就证明我的初始化确实有效
#   5. 再故意只改 0x0A 一个寄存器，看是不是它就是关键

echo "======================================================"
echo " 决定性实验：audio_cap_init.py 到底有没有用"
echo "======================================================"
echo

CAP() {
  sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/_e.raw 2>/dev/null
  sudo python3 -c "
import array, math
a = array.array('i'); a.frombytes(open('/tmp/_e.raw','rb').read())
for i in range(len(a)):
    if a[i] >= 0x800000: a[i] -= 0x1000000
L = a[0::2]
rms = math.sqrt(sum(float(x)*x for x in L)/len(L))
db = 20*math.log10(rms/8388608.0) if rms>0 else -999
print('    L = %.1f dBFS   峰值=%d   %s' % (db, max(abs(x) for x in L),
      '★ 有信号' if db > -100 else '静音'))
"
}

I2C() {
  # $1=reg $2=val
  sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR)
fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([$1, $2]))
os.write(fd, bytes([$1]))
print('    0x%02X -> 0x%02X' % ($1, os.read(fd,1)[0]))
os.close(fd)
"
}

echo "【0】现状（应该是好的）"
CAP

echo
echo "【1】★ 故意弄坏：0x03=0xF9（ADC 断电）0x0A=0x50（选 LINE 输入）"
I2C 0x03 0xF9
I2C 0x0A 0x50
echo "  再录："
CAP

echo
echo "【2】★ 跑 audio_cap_init.py（应该能修回来）"
sudo python3 /home/zynq/audio_cap_init.py 2>&1 | grep -E "0x03|0x0A|0x09|完成|✗" | head -6
echo "  再录："
CAP

echo
echo "【3】再弄坏，这次只改 0x0A（其他保持正确）"
I2C 0x0A 0x50
echo "  再录："
CAP

echo
echo "【4】只改回 0x0A = 0x00（不跑完整初始化）"
I2C 0x0A 0x00
echo "  再录："
CAP

echo
echo "======================================================"
echo " 判读"
echo "======================================================"
echo "  ★ 如果【2】修回来了、【3】又坏了、【4】又好了"
echo "    ⇒ 关键就是 0x0A 这一个寄存器（选麦克风输入）"
echo "  ★ 如果【2】修回来但【3】【4】没变化"
echo "    ⇒ 是别的寄存器在起作用"
echo "  ★ 如果【2】也没修回来"
echo "    ⇒ 我的初始化无效，PL 那边还有状态需要配"
