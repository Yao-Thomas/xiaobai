echo "=== 1) audio_alsa_svc.py 启动时做了什么 ==="
head -60 /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 2) 它有没有碰 PL 寄存器 ==="
grep -nE "0x43C|audio_pl|I2S|formatter|PL|mmap|dev/mem" /home/zynq/ui/audio_alsa_svc.py | head -20