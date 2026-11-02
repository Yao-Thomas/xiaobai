#!/bin/bash
# 跑双盲自证（必须先停音频服务，硬件是独占的）
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
cd /home/zynq/ui || exit 1
sudo python3 loopback_proof.py 2>&1 | grep -v '^\[dma\]\|^\[fmt\]\|^\[cfg\]\|^\[codec\]\|^\[i2s\]' | tail -50
echo
echo "--- 恢复音频服务 ---"
sudo systemctl start zynq-audio
sleep 5
systemctl is-active zynq-audio
