#!/bin/sh
# verify_capfix.sh —— 验证采集修复固化了没有
#
# 期望：
#   1. 先故意把 0x0A 弄坏（0x50）
#   2. 重启 zynq-audio 服务
#   3. 0x0A 应该被 ExecStartPre 自动改回 0x00
#   4. 录音应该有信号

echo "======================================================"
echo " 验证采集修复是否固化进服务"
echo "======================================================"
echo

CAP() {
  sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/_v.raw 2>/dev/null
  sudo python3 -c "
import array, math
a = array.array('i'); a.frombytes(open('/tmp/_v.raw','rb').read())
for i in range(len(a)):
    if a[i] >= 0x800000: a[i] -= 0x1000000
L = a[0::2]
rms = math.sqrt(sum(float(x)*x for x in L)/len(L))
db = 20*math.log10(rms/8388608.0) if rms>0 else -999
print('    L = %.1f dBFS   峰值=%-8d %s' % (db, max(abs(x) for x in L),
      '★ 有信号' if db > -100 else '★ 静音'))
"
}

REG() {
  sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([0x0A])); print('    0x0A = 0x%02X' % os.read(fd,1)[0]); os.close(fd)
"
}

echo "【1】先故意弄坏 0x0A"
sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([0x0A, 0x50])); os.close(fd)
"
REG
echo "  录音:"
CAP

echo
echo "【2】重启 zynq-audio（应该自动修好 0x0A）"
sudo systemctl daemon-reload
sudo systemctl restart zynq-audio
sleep 6
echo "  服务: $(systemctl is-active zynq-audio)"
REG
echo "  录音:"
CAP

echo
echo "【3】再看守护日志里 drop-in 有没有被执行"
sudo journalctl -u zynq-audio --no-pager --since "-60s" 2>/dev/null | grep -iE "ExecStartPre|audio_cap_init|error|fail" | tail -6

echo
echo "======================================================"
if [ "$(sudo python3 -c "
import fcntl, os
fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
os.write(fd, bytes([0x0A])); print(os.read(fd,1)[0]); os.close(fd)
")" = "0" ]; then
  echo " ★★★ 修复已固化：重启服务后 0x0A 自动回到 0x00"
  echo "      ⇒ 以后录音/声学自测不会再变静音"
else
  echo " ★ drop-in 没生效，需要换个做法"
fi
echo "======================================================"
