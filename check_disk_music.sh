#!/usr/bin/env bash
echo "=== 1) 磁盘占用 ==="
df -h / /home /tmp 2>/dev/null | head -6
echo
echo "=== 2) 音乐目录明细（按大小）==="
du -a /home/zynq/Music/ 2>/dev/null | sort -rn | head -20 | awk '{printf "  %8.1f MB  %s\n", $1/1024, $2}'
echo
echo "=== 3) /home/zynq 下的大文件 ==="
find /home/zynq -maxdepth 1 -type f -size +500k 2>/dev/null | while read f; do
  printf "  %8.1f MB  %s\n" "$(stat -c%s "$f" | awk '{print $1/1048576}')" "$f"
done
echo
echo "=== 4) /tmp 里的录音/临时文件 ==="
find /tmp -maxdepth 1 -type f \( -name "*.wav" -o -name "alsa_*" -o -name "cap_*" -o -name "rec_*" \) 2>/dev/null | while read f; do
  printf "  %8.2f MB  %s\n" "$(stat -c%s "$f" | awk '{print $1/1048576}')" "$f"
done
echo
echo "=== 5) 提示音目录（App 用的）==="
du -sh /home/zynq/Music/提示音 2>/dev/null | awk '{print "  "$1"  "$2}'
ls /home/zynq/Music/提示音/ 2>/dev/null | head -5 | sed 's/^/    /'
echo
echo "=== 6) 应用是怎么读音乐目录的（看有没有删除功能）==="
grep -n "def scan\|unlink\|remove\|os.remove\|删除" /home/zynq/ui/apps_music.py | head -10
