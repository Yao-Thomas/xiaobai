#!/bin/bash
echo "=== 1) ALSA 声卡（Codex 重建内核/DT 后）==="
cat /proc/asound/cards 2>&1
echo
echo "=== 2) aplay -l ==="
aplay -l 2>&1 | head -12
echo
echo "=== 3) 音频服务现在跑的是哪个脚本 ==="
systemctl cat zynq-audio 2>/dev/null | grep -E "ExecStart|WorkingDirectory"
echo "  is-active: $(systemctl is-active zynq-audio)"
echo
echo "=== 4) 相关文件 ==="
ls -l /home/zynq/ui/audio_alsa_svc.py /home/zynq/ui/audio_svc.py 2>&1
echo
echo "=== 5) asound.conf ==="
cat /etc/asound.conf 2>/dev/null | head -30
echo
echo "=== 6) bitstream 哈希（应为原版 8b1941...）==="
sha256sum /mnt/boot/system.bit 2>/dev/null
ls -l /mnt/boot/system.bit* 2>/dev/null
echo
echo "=== 7) 混音器当前值 ==="
amixer -c 0 sget 'Playback' 2>&1 | tail -3
amixer -c 0 sget 'Output 1' 2>&1 | tail -3
amixer -c 0 sget 'Output 2' 2>&1 | tail -3
echo
echo "=== 8) 内核/DT（实验版）==="
uname -r
ls -l /mnt/boot/zImage* /mnt/boot/system.dtb* 2>/dev/null