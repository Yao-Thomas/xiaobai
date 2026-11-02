#!/bin/bash
# 立刻静音并把板子放回安全状态（用户要求停手）
echo "=== 1) 停止音频服务 ==="
sudo systemctl stop zynq-audio
sleep 2
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo
echo "=== 2) 杀掉可能的播放进程 ==="
sudo pkill -f 'audio_svc|play|tone' 2>/dev/null
echo "  done"
echo
echo "=== 3) 硬件层静音 ==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, I2C, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0)
    m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  I2S CORE_CTRL 写 0 后读回: %d / %d"
          % (m.rd(I2S_BASE, I2S_CORE_CTRL), m.rd(I2S_RX_BASE, I2S_CORE_CTRL)))
    m.close()
    i = I2C()
    from audio_pl import es8388_set_vol
    es8388_set_vol(i, 0, 0xC0)          # 输出音量 0 + DAC -96dB
    print("  DAC 0x1A/0x1B = 0x%02X/0x%02X (静音)  输出音量=%d"
          % (i.rd(0x1A), i.rd(0x1B), i.rd(0x2E) & 0x3F))
    i.close()
except Exception as e:
    print("  失败:", e)
PY
echo
echo "=== 4) 上静音锁（防止 Agent 再放音）==="
sudo tee /etc/zynq-silent > /dev/null <<'EOF'
用户已要求停手，交给 Codex 接手。
在他本人同意前不许发出任何声音。
EOF
echo -n "  /etc/zynq-silent: "; [ -f /etc/zynq-silent ] && echo 存在
echo
echo "=== 5) 最终状态 ==="
echo -n "  zynq-agent  : "; systemctl is-active zynq-agent
echo -n "  zynq-audio  : "; systemctl is-active zynq-audio
echo -n "  zynq-desktop: "; systemctl is-active zynq-desktop
echo -n "  静音锁      : "; [ -f /etc/zynq-silent ] && echo 生效
