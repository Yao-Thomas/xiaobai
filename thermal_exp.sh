#!/bin/sh
# thermal_exp.sh —— 受控实验：停桌面能不能降温
#
# 背景：板子空载 load≈0.3，温度却从 70 一路爬到 77+ 还在涨。
#       没有风扇、没有 cpufreq —— 只能靠"停活"降温。
#       这个实验就是要量出"停桌面"到底能降几度。
#
# 步骤：
#   A 基线（桌面在跑）  记 90 秒
#   B 停桌面            记 150 秒
#   C 起回桌面          记 60 秒
#
# 注意：整个实验约 5 分钟，期间屏幕会黑（桌面停了）。

TEMP() { /usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null; }

sample() {
  label="$1"; n="$2"; gap="$3"
  echo "--- $label ---"
  i=0
  while [ $i -lt $n ]; do
    t=$(TEMP)
    l=$(cut -d' ' -f1 /proc/loadavg)
    echo "  $(date +%H:%M:%S)  ${t}°C  load=${l}"
    i=$((i+1))
    sleep $gap
  done
}

echo "======================================================"
echo " 温度受控实验：停桌面能不能降温"
echo "======================================================"
echo

echo "A) 基线：桌面在跑（先让守护别插手）"
sudo systemctl stop thermal-guard 2>/dev/null
sleep 1
sample "基线 90 秒" 18 5

echo
echo "B) ★ 停桌面"
sudo systemctl stop zynq-desktop
sleep 3
sample "停桌面后 150 秒" 25 6

echo
echo "C) 起回桌面"
sudo systemctl start zynq-desktop
sleep 5
sample "恢复桌面后 60 秒" 10 6

echo
echo "D) 起回温度守护"
sudo systemctl start thermal-guard
sleep 2
echo "  thermal-guard: $(systemctl is-active thermal-guard)"
echo "  zynq-desktop:  $(systemctl is-active zynq-desktop)"
