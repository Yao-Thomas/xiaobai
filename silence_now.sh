#!/bin/bash
echo "=== 1) 停掉音频服务（独占设备，停了就不可能再出声）==="
sudo systemctl stop zynq-audio
sleep 2
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo
echo "=== 2) 杀掉所有可能在碰音频的进程 ==="
for pat in loopback_proof matrix_vol matrix_repeat mic_stability chime_proof voice_selftest rec_ test_audio beep reg03 instability; do
  P=$(pgrep -f "$pat" 2>/dev/null)
  if [ -n "$P" ]; then echo "  杀掉 $pat: $P"; sudo kill -9 $P 2>/dev/null; fi
done
echo "  (没列出来就是没有)"
echo
echo "=== 3) 还剩哪些 python 在跑 ==="
ps aux | grep -E "python" | grep -v grep | awk '{print "  " $2, $11, $12, $13}'
echo
echo "=== 4) 确认 I2S 发送器已经关掉（硬件层面别再出声）==="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, FMT_BASE, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    # 把两个 I2S 核都关掉
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0)
    m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  已写 0 到 I2S 发送器/接收器的 CORE_CTRL")
    print("  读回 I2S_TX CORE_CTRL =", m.rd(I2S_BASE, I2S_CORE_CTRL))
    print("  读回 I2S_RX CORE_CTRL =", m.rd(I2S_RX_BASE, I2S_CORE_CTRL))
    m.close()
except Exception as e:
    print("  (I2S 关闭失败:", e, ")")
PY
echo
echo "=== 5) 最终状态 ==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  zynq-agent: "; systemctl is-active zynq-agent
echo "  ★ 音频服务已停，从现在起不会再有声音，直到你说继续"