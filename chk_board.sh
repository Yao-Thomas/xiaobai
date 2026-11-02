#!/bin/sh
# chk_board.sh —— 板子一上电先看一遍现状
echo "======================================================"
echo " 板子现状"
echo "======================================================"
echo
echo "--- 基本 ---"
hostname
uptime | sed 's/^ *//'
echo
echo "--- IP ---"
hostname -I
echo
echo "--- 温度 ---"
sudo /usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null || echo "读不到"
echo
echo "--- 服务 ---"
for s in zynq-desktop zynq-audio zynq-agent thermal-guard thermal-cooldown; do
  printf "  %-20s %s\n" "$s" "$(systemctl is-active $s)"
done
echo
echo "--- ★ 今天要部署的文件在不在（判断是不是旧版）---"
for f in cloud_api.py scope_capture.py fpga_build_daemon.py audio_cap_init.py \
         agent/tiers.py agent/sessions.py agent/hw_tools.py \
         ui/apps_hwchange.py install_cloud_api.sh; do
  if [ -f "/home/zynq/$f" ]; then
    printf "  ✓ %-24s %s 字节\n" "$f" "$(stat -c %s /home/zynq/$f)"
  else
    printf "  ✗ %-24s 不在\n" "$f"
  fi
done
echo
echo "--- ★ 当前硬件状态（回归用）---"
echo -n "  scope_0 VERSION: "
sudo /usr/bin/python3 - <<'PY'
import mmap, os, struct
def rd(base, off):
    try:
        fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
        m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        v = struct.unpack_from('<I', m, off)[0]
        m.close(); os.close(fd); return '0x%08X' % v
    except Exception as e:
        return '读不到(%s)' % type(e).__name__
print(rd(0x43CC0000, 0x34))
print('  gpu_0   VERSION:', rd(0x43CB0000, 0x34))
print('  CNN conv_pool   :', rd(0x43CD0000, 0x00))
print('  CNN fc          :', rd(0x43CE0000, 0x00))
PY
echo
echo "--- ES8388 的 0x0A（0x00=麦克风）---"
sudo python3 -c "
import fcntl, os
try:
    fd = os.open('/dev/i2c-1', os.O_RDWR); fcntl.ioctl(fd, 0x0706, 0x10)
    os.write(fd, bytes([0x0A])); print('  0x0A = 0x%02X' % os.read(fd,1)[0]); os.close(fd)
except Exception as e:
    print('  读不到:', e)
"
echo
echo "--- 音频采集现在有没有信号（2 秒）---"
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/_chk.raw 2>/dev/null
sudo python3 -c "
import array, math
try:
    a = array.array('i'); a.frombytes(open('/tmp/_chk.raw','rb').read())
    for i in range(len(a)):
        if a[i] >= 0x800000: a[i] -= 0x1000000
    L = a[0::2]
    rms = math.sqrt(sum(float(x)*x for x in L)/len(L))
    db = 20*math.log10(rms/8388608.0) if rms>0 else -999
    print('  L = %.1f dBFS  峰值 %d  %s' % (db, max(abs(x) for x in L),
          '★ 有信号' if db > -100 else '★ 静音'))
except Exception as e:
    print('  分析失败:', e)
"
echo
echo "--- 变更单有几条 ---"
sudo wc -l /var/lib/hwchange/changes.jsonl 2>/dev/null || echo "  还没有变更单"
echo
echo "--- 云协同服务在不在 ---"
systemctl is-active cloud-api 2>/dev/null || echo "  (cloud-api 还没装)"
