#!/bin/bash
# 停掉服务，用已验证的 rec_big.py 复测，判断差异在代码还是在硬件状态
sudo pkill -f audio_svc.py 2>/dev/null
sleep 1.5
echo "--- 服务已停 ---"
pgrep -af audio_svc.py
cd /home/zynq/ui || exit 1
echo "=== rec_big.py 复测 (amp0.9 vol30 PGA0x66 0x03=0x59 0x0A=0x00) ==="
sudo python3 rec_big.py --freq 1000 --secs 0.5 2>&1 | tail -22
