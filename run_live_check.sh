#!/bin/bash
# 服务保持运行（只读寄存器，不抢设备）
echo -n "zynq-audio: "; systemctl is-active zynq-audio
cd /home/zynq/ui || exit 1
sudo python3 -u live_check.py 2>&1