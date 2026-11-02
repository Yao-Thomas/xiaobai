#!/bin/bash
# 紧急静音 + 上锁（防止 Agent 自己再放音）
echo "===== 1) 立刻停音频服务 ====="
sudo systemctl stop zynq-audio
sleep 2
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo
echo "===== 2) 杀掉所有播放动作 ====="
sudo pkill -f 'loopback|selftest|matrix|play|beep|chime' 2>/dev/null
echo "  done"
echo
echo "===== 3) 硬件层也关掉 I2S ====="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0)
    m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  I2S TX/RX CORE_CTRL 已写 0，读回:",
          m.rd(I2S_BASE, I2S_CORE_CTRL), m.rd(I2S_RX_BASE, I2S_CORE_CTRL))
    m.close()
except Exception as e:
    print("  (跳过:", e, ")")
PY
echo
echo "===== 4) 上「静音锁」：Agent 不许再放音 ====="
sudo tee /etc/zynq-silent > /dev/null <<'EOF'
用户明确要求：在他本人同意之前，任何声音都不许发出来。
放音前必须单独请示并等待回复。
EOF
sudo chmod 644 /etc/zynq-silent
echo "  已创建 /etc/zynq-silent"
echo
echo "===== 5) 禁止 zynq-audio 被自动拉起 ====="
sudo systemctl disable zynq-audio 2>&1 | tail -2
echo -n "  enabled? "; systemctl is-enabled zynq-audio 2>&1
echo
echo "===== 6) 最终状态 ====="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  zynq-agent: "; systemctl is-active zynq-agent