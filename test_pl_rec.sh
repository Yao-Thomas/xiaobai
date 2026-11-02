#!/bin/sh
# test_pl_rec.sh —— 用原来的 PL 路径录音（rec_big.py）
#
# 为什么要先停 zynq-audio：
#   现在跑的是 audio_alsa_svc.py（ALSA 版），它会用内核 I2S 驱动；
#   而 rec_big.py 走的是 audio_pl.py（PL 寄存器全用户态）。
#   两条路都碰同一套 PL 寄存器，同时跑会互相踩。
#
# ★ 测完一定要把服务起回来。

set +e

echo "=== 0) 现状 ==="
systemctl is-active zynq-audio

echo
echo "=== 1) 停音频服务（让出 PL 音频寄存器）==="
sudo systemctl stop zynq-audio
sleep 1
echo "  zynq-audio: $(systemctl is-active zynq-audio)"

echo
echo "=== 2) 跑 rec_big.py（原始 PL 录音工具）==="
cd /home/zynq/ui
sudo timeout 90 python3 rec_big.py 2>&1 | head -60
echo "  (退出码 $?)"

echo
echo "=== 3) 起回音频服务 ==="
sudo systemctl start zynq-audio
sleep 3
echo "  zynq-audio: $(systemctl is-active zynq-audio)"
