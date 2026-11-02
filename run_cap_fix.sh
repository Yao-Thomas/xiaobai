#!/bin/bash
cd /home/zynq/ui || exit 1
sudo python3 -u cap_fix_test.py 2>&1 | grep -vE "^\[dma\]|^\[codec\]|^\[i2s\]|^\[cfg\]"