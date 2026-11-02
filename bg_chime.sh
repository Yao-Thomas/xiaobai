#!/bin/bash
# 用提示音做极短声学自证。★ 无论成败都恢复音频服务。
LOG=/tmp/chime.log
sudo pkill -f chime_proof.py 2>/dev/null
sleep 1
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
: > $LOG
{
  cd /home/zynq/ui
  python3 -u chime_proof.py
  echo "EXIT=$?"
} >> $LOG 2>&1
sudo systemctl start zynq-audio
sleep 6
echo "SERVICE=$(systemctl is-active zynq-audio)" >> $LOG
echo "ALLDONE" >> $LOG