#!/bin/bash
echo "=== 只读检查（不改动）==="
sudo bash /tmp/codec_reset.sh --check
echo
echo "=== 恢复 ==="
sudo bash /tmp/codec_reset.sh
echo
echo "=== 确认音频服务仍然停着（恢复寄存器不会出声）==="
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  静音锁    : "; [ -f /etc/zynq-silent ] && echo 生效