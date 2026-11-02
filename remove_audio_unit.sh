#!/bin/bash
echo "===== 1) 停服务 + 把单元文件移走 ====="
sudo systemctl stop zynq-audio
sleep 2
if [ -f /etc/systemd/system/zynq-audio.service ]; then
  sudo mv /etc/systemd/system/zynq-audio.service /root/zynq-audio.service.disabled
  echo "  已移到 /root/zynq-audio.service.disabled"
fi
# 清掉所有 wants 软链
sudo rm -f /etc/systemd/system/multi-user.target.wants/zynq-audio.service 2>/dev/null
sudo systemctl daemon-reload
sleep 1
echo
echo "===== 2) 验证：现在 start 应该失败 ====="
sudo systemctl start zynq-audio 2>&1 | head -3
sleep 1
echo -n "  is-active: "; systemctl is-active zynq-audio
echo
echo "===== 3) 硬件层再关 I2S ====="
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    m = Mem()
    m.wr(I2S_BASE, I2S_CORE_CTRL, 0); m.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
    print("  I2S CORE_CTRL:", m.rd(I2S_BASE, I2S_CORE_CTRL),
          m.rd(I2S_RX_BASE, I2S_CORE_CTRL))
    m.close()
except Exception as e:
    print("  (跳过:", e, ")")
PY
echo
echo "===== 4) 最终 ====="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  zynq-agent: "; systemctl is-active zynq-agent
echo -n "  zynq-desktop: "; systemctl is-active zynq-desktop
echo "  ★ 恢复方法：sudo mv /root/zynq-audio.service.disabled /etc/systemd/system/zynq-audio.service && sudo systemctl daemon-reload && sudo systemctl start zynq-audio"