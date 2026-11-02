#!/usr/bin/env bash
echo "=== 1) 哪些 .bit/.bin 被 UI 代码引用 ==="
for f in scope.bit gpu_final.bit.bin gpu_system.bit.bin gpu_system_swapped.bit.bin \
         gpu2026_fullbit.bit system_rxbclk.bit system_wrapper_audio_clockfix.bit \
         root.xwd music_packed.bin craft_src.tar.gz; do
  n=$(grep -rl "$f" /home/zynq/ui/*.py 2>/dev/null | wc -l)
  printf "  %-42s 被 %d 个 UI 文件引用\n" "$f" "$n"
  if [ "$n" -gt 0 ]; then
    grep -rl "$f" /home/zynq/ui/*.py 2>/dev/null | head -3 | sed 's/^/       /'
  fi
done
echo
echo "=== 2) 截图 PNG 有没有被引用 ==="
for f in /home/zynq/*.png; do
  b=$(basename "$f")
  n=$(grep -rl "$b" /home/zynq/ui/*.py 2>/dev/null | wc -l)
  printf "  %-42s 被 %d 个 UI 文件引用  %.1f MB\n" "$b" "$n" "$(stat -c%s "$f" | awk '{print $1/1048576}')"
done
echo
echo "=== 3) 备份的内核镜像 ==="
ls -l /home/zynq/zImage_es8388* 2>/dev/null | awk '{printf "  %.1f MB  %s\n", $5/1048576, $9}'
echo "  （/mnt/boot 下的内核备份:）"
ls -l /mnt/boot/zImage* 2>/dev/null | awk '{printf "  %.1f MB  %s\n", $5/1048576, $9}'
echo
echo "=== 4) 总账：/home/zynq 下我的垃圾有多少 ==="
du -sh /home/zynq/*.png /home/zynq/root.xwd /home/zynq/system_rxbclk.bit \
       /home/zynq/system_wrapper_audio_clockfix.bit /home/zynq/卡农_响.wav 2>/dev/null |
  awk '{printf "  %8s  %s\n", $1, $2}' | head -20
echo
du -ch /home/zynq/*.png /home/zynq/root.xwd /home/zynq/system_rxbclk.bit \
       /home/zynq/system_wrapper_audio_clockfix.bit /home/zynq/卡农_响.wav 2>/dev/null |
  tail -1 | awk '{print "  合计: "$1}'
