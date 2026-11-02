#!/bin/bash
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
sudo systemctl start zynq-audio
sleep 6
echo "=== 复跑已知可用的 mic_beep_proof.py（经音频服务）==="
cd /home/zynq/ui && sudo python3 mic_beep_proof.py 2>&1 | tail -12
echo
echo "=== 直接查 ES8388 全部寄存器（看 ADC 那部分现在是什么状态）==="
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
sudo python3 /home/zynq/ui/es8388_regs.py 2>&1 | tail -10
sudo systemctl start zynq-audio
sleep 5
systemctl is-active zynq-audio
