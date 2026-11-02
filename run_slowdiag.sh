#!/bin/bash
sudo systemctl stop zynq-audio
sleep 2
cd /home/zynq/ui || exit 1
echo "★ 播放中（补偿慢12倍），请听：应该是正常速度的《小星星》，但音色偏闷"
sudo python3 -u slowdiag_play.py 2>&1 | grep -vE "^\[dma\]|^\[fmt\]|^\[codec\]|^\[i2s\]|^\[cfg\]"
echo
sudo systemctl start zynq-audio
sleep 3
echo -n "  zynq-audio: "; systemctl is-active zynq-audio