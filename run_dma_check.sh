#!/bin/bash
sudo systemctl stop zynq-audio
sleep 2
cd /home/zynq/ui || exit 1
sudo python3 -u dma_check.py 2>&1 | grep -vE "^\[dma\]|^\[fmt\]"
echo
sudo systemctl start zynq-audio
sleep 3
echo -n "  zynq-audio: "; systemctl is-active zynq-audio