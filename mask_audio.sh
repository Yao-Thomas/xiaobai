#!/bin/bash
echo "===== 1) 停 + mask（mask 之后连 root 的 systemctl start 都会失败）====="
sudo systemctl stop zynq-audio
sleep 2
sudo systemctl mask zynq-audio 2>&1 | tail -2
echo -n "  is-active : "; systemctl is-active zynq-audio
echo -n "  is-enabled: "; systemctl is-enabled zynq-audio 2>&1
echo
echo "===== 2) 验证：显式 start 应该失败 ====="
sudo systemctl start zynq-audio 2>&1 | head -3
sleep 1
echo -n "  start 之后 is-active: "; systemctl is-active zynq-audio
echo
echo "===== 3) 硬件层再关一次 I2S ====="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0)
    m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  I2S CORE_CTRL 读回:", m.rd(I2S_BASE, I2S_CORE_CTRL),
          m.rd(I2S_RX_BASE, I2S_CORE_CTRL))
    m.close()
except Exception as e:
    print("  (跳过:", e, ")")
PY
echo
echo "===== 4) 最终 ====="
echo -n "  zynq-audio : "; systemctl is-active zynq-audio
echo -n "  zynq-agent : "; systemctl is-active zynq-agent
echo "  ★ 现在连 root 都启动不了音频服务，必须 systemctl unmask 才行"