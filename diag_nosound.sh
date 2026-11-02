#!/bin/bash
# 诊断：为什么没声音
echo "=== 1) 两个 I2S 核的当前状态 ==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
m = Mem()
tx = m.rd(I2S_BASE, I2S_CORE_CTRL)
rx = m.rd(I2S_RX_BASE, I2S_CORE_CTRL)
print("  TX CORE_CTRL = %d  %s" % (tx, "★关着(没BLCK=没声音)" if tx == 0 else "开着"))
print("  RX CORE_CTRL = %d  %s" % (rx, "★关着" if rx == 0 else "开着"))
m.close()
PY
echo
echo "=== 2) codec 寄存器 ==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import I2C
i = I2C()
for r, n in ((0x1A,"DAC数字音量L"), (0x1B,"DAC数字音量R"),
             (0x27,"DAC->左混合器"), (0x2A,"DAC->右混合器"),
             (0x2E,"LOUT1"), (0x2F,"ROUT1"), (0x30,"LOUT2(喇叭)"),
             (0x31,"ROUT2(喇叭)"), (0x02,"chip power"),
             (0x00,"chip ctrl1"), (0x01,"chip ctrl2")):
    print("  0x%02X %-14s = 0x%02X" % (r, n, i.rd(r)))
i.close()
PY
echo
echo "=== 3) 服务状态 ==="
curl -s --max-time 10 http://127.0.0.1:8767/state; echo
echo
echo "=== 4) 服务进程 ==="
ps aux | grep -E "audio_svc" | grep -v grep | head -2 | awk '{print "  PID "$2"  "$11" "$12}'
echo
echo "=== 5) MD8002A 功放相关（看有没有可控制的 GPIO）==="
ls /sys/class/gpio/ 2>/dev/null | head -5
echo
echo "=== 6) 手动把两个核打开，再放一次 ==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
m = Mem()
m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 1)
m.wr(I2S_BASE, I2S_CORE_CTRL, 1)
print("  写入后: TX=%d RX=%d" % (m.rd(I2S_BASE, I2S_CORE_CTRL),
                                m.rd(I2S_RX_BASE, I2S_CORE_CTRL)))
m.close()
PY
