#!/bin/bash
echo "=== 1) 关掉 I2S 两个核 ==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0)
    m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  CORE_CTRL 写 0 后读回: %d / %d"
          % (m.rd(I2S_BASE, I2S_CORE_CTRL), m.rd(I2S_RX_BASE, I2S_CORE_CTRL)))
    m.close()
except Exception as e:
    print("  失败:", e)
PY
echo
echo "=== 2) 确认 DAC 仍然静音（保留，多重保险）==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import I2C
i = I2C()
print("  0x1A/0x1B = 0x%02X/0x%02X  %s"
      % (i.rd(0x1A), i.rd(0x1B),
         "★静音" if i.rd(0x1A) == 0xC0 else "可出声"))
i.close()
PY
echo
echo "=== 3) 确认服务封锁还在 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  单元文件  : "; [ -f /etc/systemd/system/zynq-audio.service ] && echo 原位 || echo 已移走
echo -n "  静音锁    : "; [ -f /etc/zynq-silent ] && echo 生效
echo
echo "=== 4) 现在有 5 层保险 ==="
echo "  1. 音频服务停止"
echo "  2. 单元文件移走（systemctl start 报 Unit not found）"
echo "  3. /etc/zynq-silent 静音锁（工具层 + 权限层拒绝）"
echo "  4. DAC 数字音量 0xC0 = -96dB"
echo "  5. I2S TX/RX CORE_CTRL = 0"