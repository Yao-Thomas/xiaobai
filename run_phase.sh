#!/bin/bash
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
cd /home/zynq/ui || exit 1
sudo python3 i2s_phase_test.py 2>&1 | grep -v '^\[dma\]\|^\[fmt\]\|^\[cfg\]\|^\[codec\]\|^\[i2s\]\|^\[cap\]' | tail -25
echo
sudo systemctl start zynq-audio
sleep 5
systemctl is-active zynq-audio
