#!/bin/bash
# 查厂家内核/DTB 对这块 V3.9(ES8388) 板子的支持程度
# 目的：判断"用官方驱动放音做对照"可不可行
echo "===== 0) 板子信息 ====="
cat /proc/device-tree/model 2>/dev/null | tr -d '\0'; echo
uname -a
echo

echo "===== 1) 内核里有没有 ES8388 的 ASoC 驱动 ====="
KD=/lib/modules/$(uname -r)
echo "--- .ko 文件 ---"
find $KD -iname "*8388*" -o -iname "*8960*" 2>/dev/null | head -20
echo "(空 = 没有现成模块，可能是编进内核了)"
echo
echo "--- 内核配置里有没有打开 ---"
for f in /boot/config-$(uname -r) /proc/config.gz; do
  if [ -f "$f" ]; then
    echo "  来源: $f"
    if [[ "$f" == *.gz ]]; then zcat $f | grep -iE "SND_SOC_ES8388|SND_SOC_WM8960|SND_SOC_ZYNQ" ; else grep -iE "SND_SOC_ES8388|SND_SOC_WM8960|SND_SOC_ZYNQ" $f; fi
  fi
done
echo

echo "===== 2) 内核里有没有 es8388 的符号（编进内核也会有）====="
if [ -r /proc/kallsyms ]; then
  grep -icE "es8388" /proc/kallsyms 2>/dev/null | sed 's/^/  kallsyms 里 es8388 符号数: /'
  grep -icE "wm8960" /proc/kallsyms 2>/dev/null | sed 's/^/  kallsyms 里 wm8960 符号数: /'
fi
modprobe -n snd-soc-es8388 2>&1 | head -2
modprobe -n snd-soc-wm8960 2>&1 | head -2
echo

echo "===== 3) DTB 里声明的是什么 codec ====="
for d in /proc/device-tree/amba*/*i2c*/*; do
  if [ -f "$d/compatible" ]; then
    c=$(tr -d '\0' < "$d/compatible")
    case "$c" in
      *8388*|*8960*|*codec*|*audio*) echo "  $d"; echo "      compatible = $c";;
    esac
  fi
done
echo "--- 用字符串直接搜 ---"
strings /sys/firmware/fdt 2>/dev/null | grep -iE "es8388|wm8960" | sort -u | head
echo

echo "===== 4) ALSA 现在看到什么声卡 ====="
cat /proc/asound/cards 2>/dev/null
echo "--- codec 列表 ---"
for c in /proc/asound/card*/codec*; do
  [ -f "$c" ] && echo "  $c:" && head -3 "$c"
done 2>/dev/null
echo "--- aplay -l ---"
aplay -l 2>&1 | head -8
echo

echo "===== 5) 我们的服务状态 ====="
systemctl is-active zynq-audio zynq-agent zynq-desktop
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
