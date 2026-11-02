#!/bin/bash
cd /home/zynq || exit 1
echo "########  放 2 秒提示音，请听  ########"
sudo python3 -u play_with_bypass.py /home/zynq/Music/提示音.wav force 2>&1
echo
echo "########  再放 8 秒小星星，请听  ########"
sudo python3 -u play_with_bypass.py /home/zynq/Music/03_小星星.wav force 2>&1 | tail -20