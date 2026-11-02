echo "=== 1) 原版录音工具还在吗 ==="
ls -la /home/zynq/rec_big.py /home/zynq/instability_silent.py /home/zynq/pitch_check2.py 2>/dev/null
ls -la /home/zynq/*.py 2>/dev/null | head -25
echo
echo "=== 2) 音频勘验目录 ==="
ls -la /home/zynq/14_音频勘验/ 2>/dev/null || find /home/zynq -maxdepth 2 -iname "*音频勘验*" 2>/dev/null
echo
echo "=== 3) PL 音频 IP 的地址和状态 ==="
for a in 0x43C50000 0x43C60000 0x43C70000; do
  printf "  %s: " $a
  sudo devmem2 $a 2>/dev/null | tail -1 || echo "(没 devmem2)"
done
echo
echo "=== 4) audio_direct / pl 音频模块 ==="
ls -la /home/zynq/ui/audio_pl.py /home/zynq/ui/audio_svc.py 2>/dev/null
echo
echo "=== 5) zynq-audio 服务是什么 ==="
systemctl cat zynq-audio 2>/dev/null | grep -E "ExecStart|Description"