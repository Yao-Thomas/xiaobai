#!/bin/bash
echo "=== audio_alsa_svc.py 的 play_file 实现 ==="
grep -n "def play_file" -A 40 /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== stop() 实现 ==="
grep -n "def stop" -A 18 /home/zynq/ui/audio_alsa_svc.py