#!/bin/bash
cd /home/zynq/ui || exit 1
sudo python3 -u cap_diag.py 2>&1 | grep -vE "^\[dma\]|^\[fmt\]|^\[codec\]|^\[i2s\]|^\[cfg\]"