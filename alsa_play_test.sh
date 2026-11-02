#!/bin/bash
# 放《小星星》并同时抓 formatter/I2S 寄存器（ALSA 路径）
echo "=== 播放前状态 ==="
echo -n "  声卡: "; cat /proc/asound/cards 2>/dev/null | head -1
amixer -c 0 sget 'Output 1' 2>&1 | tail -1
amixer -c 0 sget 'Output 2' 2>&1 | tail -1
echo
echo "=== 开始播放（aplay 后台），同时抓寄存器 ==="
sudo pkill -f 'aplay' 2>/dev/null
sleep 1

# 后台起 aplay
aplay -q /home/zynq/Music/03_小星星.wav &
APLAY=$!
echo "  aplay PID=$APLAY"
sleep 0.8

# 播放中抓 6 次
sudo python3 - <<'PY'
import sys, time
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, FMT_BASE, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL, MM2S
    m = Mem()
    R_CTRL = MM2S + 0x10
    R_STS  = MM2S + 0x14
    R_XFER = MM2S + 0x28
    print("  %-8s %-12s %-12s %-10s %-8s %-8s" %
          ("t(s)", "MM2S_CTRL", "MM2S_STS", "MM2S_XFER", "TX_CORE", "RX_CORE"))
    print("  " + "-" * 62)
    t0 = time.time()
    prev = None
    for k in range(10):
        c = m.rd(FMT_BASE, R_CTRL)
        s = m.rd(FMT_BASE, R_STS)
        x = m.rd(FMT_BASE, R_XFER)
        tx = m.rd(I2S_BASE, I2S_CORE_CTRL)
        rx = m.rd(I2S_RX_BASE, I2S_CORE_CTRL)
        d = "" if prev is None else " (+%d)" % (x - prev)
        print("  %-8.2f 0x%08X   0x%08X   0x%08X%s  %-8d %-8d"
              % (time.time() - t0, c, s, x, d, tx, rx))
        prev = x
        time.sleep(0.45)
    m.close()
except Exception as e:
    print("  抓取失败:", e)
PY

echo
wait $APLAY 2>/dev/null
echo "  aplay 退出码: $?"
echo
echo "=== 播放后 ==="
sudo python3 -c "
import sys
sys.path.insert(0, '/home/zynq/ui')
from audio_pl import Mem, FMT_BASE, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL, MM2S
m = Mem()
print('  MM2S_CTRL = 0x%08X' % m.rd(FMT_BASE, MM2S + 0x10))
print('  TX/RX CORE_CTRL = %d / %d' % (m.rd(I2S_BASE, I2S_CORE_CTRL),
                                        m.rd(I2S_RX_BASE, I2S_CORE_CTRL)))
m.close()
" 2>&1
