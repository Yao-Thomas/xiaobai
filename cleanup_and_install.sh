#!/usr/bin/env bash
echo "=== 清理前 ==="
df -h / | tail -1 | awk '{print "  根分区: 已用 "$3"  剩余 "$4"  使用率 "$5}'
du -sh /home/zynq 2>/dev/null | awk '{print "  /home/zynq: "$1}'
echo

echo "=== 1) 装带「删除」按钮的新版音乐 App ==="
sudo cp /home/zynq/ui/apps_music.py /home/zynq/ui/apps_music.py.bak_$(date +%Y%m%d_%H%M%S)
sudo cp /home/zynq/ui/apps_music_new.py /home/zynq/ui/apps_music.py
sudo chown zynq:zynq /home/zynq/ui/apps_music.py
python3 -c "import ast; ast.parse(open('/home/zynq/ui/apps_music.py').read()); print('  语法 OK')"
echo -n "  「删除」按钮存在: "
grep -c '"删除", "delete"' /home/zynq/ui/apps_music.py
echo

echo "=== 2) 删我的截图（24 张，都是调试用的）==="
n=$(ls /home/zynq/*.png 2>/dev/null | wc -l)
du -ch /home/zynq/*.png 2>/dev/null | tail -1 | awk '{print "  释放 "$1}'
rm -f /home/zynq/*.png
echo "  已删 $n 张"
echo
echo "=== 3) 删内核镜像副本（/mnt/boot 下有正式的那份）==="
ls -l /home/zynq/zImage_es8388* 2>/dev/null | awk '{printf "  %s  %.1f MB\n", $9, $5/1048576}'
rm -f /home/zynq/zImage_es8388 /home/zynq/zImage_es8388_fixed
echo "  已删"
echo
echo "=== 4) 删 root.xwd / 我上传的 bitstream 副本 / 重复的 wav ==="
rm -f /home/zynq/root.xwd
rm -f /home/zynq/system_rxbclk.bit
rm -f /home/zynq/system_wrapper_audio_clockfix.bit
rm -f /home/zynq/卡农_响.wav
rm -f /tmp/_t_*.wav /tmp/rec_after.wav /tmp/capdiag*.wav /tmp/fix_*.wav /tmp/adc_*.wav /tmp/regcap.wav /tmp/cap_*.wav 2>/dev/null
echo "  已删"
echo
echo "=== 5) 删音乐目录里我的测试音（保留小星星/语音测试/提示音）==="
cd /home/zynq/Music
for f in "01_纯音1kHz.wav" "01_纯音_1kHz.wav" "02_左右声道.wav" "03_板载录音.wav" "04_扫频.wav" "05_卡农.wav" "05_canon.wav"; do
  if [ -f "$f" ]; then
    sz=$(stat -c%s "$f")
    rm -f "$f"
    printf "  删除 %-24s (%.0f KB)\n" "$f" "$(echo "$sz/1024" | bc 2>/dev/null || echo $((sz/1024)))"
  fi
done
echo
echo "=== 清理后 ==="
df -h / | tail -1 | awk '{print "  根分区: 已用 "$3"  剩余 "$4"  使用率 "$5}'
du -sh /home/zynq 2>/dev/null | awk '{print "  /home/zynq: "$1}'
du -sh /home/zynq/Music 2>/dev/null | awk '{print "  Music: "$1}'
echo
echo "=== 剩下的音乐文件 ==="
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{printf "  %8.0f KB  %s\n", $5/1024, $9}'
echo
echo "=== 重启桌面让新 App 生效 ==="
sudo systemctl restart zynq-desktop
sleep 10
echo -n "  zynq-desktop: "; systemctl is-active zynq-desktop
