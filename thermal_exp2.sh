#!/bin/sh
# thermal_exp2.sh —— 分步降温实验（每步量 90 秒）
#
# 上一版只跑完 A 阶段就退了（可能被守护干扰）。这次：
#   · 每一阶段独立、互不干扰
#   · 每步之间留稳定时间
#   · 最后一定恢复原状
#
# 步骤：
#   A 现状（桌面 + 音频都在）
#   B 停桌面（最大的持续负载：每帧重绘 1024x600）
#   C 再降 LCD 背光（PWM）
#   D 恢复

TEMP() { /usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null; }

sample() {
  label="$1"; n="$2"
  echo "--- $label ---"
  i=0
  while [ $i -lt $n ]; do
    printf "  %s  %s°C  load=%s\n" "$(date +%H:%M:%S)" "$(TEMP)" "$(cut -d' ' -f1 /proc/loadavg)"
    i=$((i+1)); sleep 6
  done
}

echo "======================================================"
echo " 分步降温实验"
echo "======================================================"

# 先把守护停掉，免得它在中途插手，实验就不干净了
echo "（临时停掉温度守护，实验完再起回来）"
sudo systemctl stop thermal-guard
sleep 2

echo
echo "A) 现状：桌面 + 音频都在"
sample "A 基线 90 秒" 15

echo
echo "B) ★ 停桌面（持续刷屏是最大负载）"
sudo systemctl stop zynq-desktop
sleep 8
sample "B 停桌面后 90 秒" 15

echo
echo "C) ★ 再降 LCD 背光"
# 导出 pwm0 -> 设周期 -> 设占空比
if [ -d /sys/class/pwm/pwmchip0 ]; then
  echo 0 | sudo tee /sys/class/pwm/pwmchip0/export >/dev/null 2>&1
  sleep 1
  P=/sys/class/pwm/pwmchip0/pwm0
  if [ -d "$P" ]; then
    echo "  导出成功: $P"
    # 周期 20ms (50Hz)，占空比从默认改成 10%
    echo 20000000 | sudo tee $P/period >/dev/null 2>&1
    echo 2000000  | sudo tee $P/duty_cycle >/dev/null 2>&1
    echo 1        | sudo tee $P/enable >/dev/null 2>&1
    sleep 1
    echo "  period=$(cat $P/period 2>/dev/null) duty=$(cat $P/duty_cycle 2>/dev/null) enable=$(cat $P/enable 2>/dev/null)"
  else
    echo "  ★ 导出失败"
  fi
else
  echo "  ★ 没有 pwmchip0"
fi
sample "C 背光降低后 90 秒" 15

echo
echo "D) 恢复"
# 背光恢复到 100%
P=/sys/class/pwm/pwmchip0/pwm0
if [ -d "$P" ]; then
  echo 20000000 | sudo tee $P/duty_cycle >/dev/null 2>&1
  echo "  背光恢复 100%"
fi
sudo systemctl start zynq-desktop
sleep 5
sudo systemctl start zynq-audio
sleep 3
sudo systemctl start thermal-guard
sleep 2
echo "  zynq-desktop:  $(systemctl is-active zynq-desktop)"
echo "  zynq-audio:    $(systemctl is-active zynq-audio)"
echo "  thermal-guard: $(systemctl is-active thermal-guard)"
echo
echo "＝ 最后温度: $(TEMP)°C"
