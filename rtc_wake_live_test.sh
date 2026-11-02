#!/bin/sh
# rtc_wake_live_test.sh —— 实机验证「RTC 唤醒」
#
# ★ 这是有风险的一步：
#   如果 RTC 唤醒不生效，板子会停在关机状态，需要物理断电才能恢复。
#   但这也正是用户要求的"关机休息一段时间"的状态，所以风险可接受。
#
# 计划：
#   1. 记下当前温度和状态
#   2. 设 RTC 闹钟 = 现在 + 180 秒
#   3. poweroff
#   4. （从 PC 侧等它自己回来）
#
# 如果 3 分钟后板子 ping 通 -> ★ 唤醒成功，可以做自动轮休
# 如果 6 分钟后还不通    -> 唤醒失败，需要人工上电

echo "======================================================"
echo " RTC 唤醒实机测试"
echo "======================================================"

echo
echo "【1】关机前的状态"
date
echo "  温度: $(/usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null) °C"
uptime
echo "  服务: desktop=$(systemctl is-active zynq-desktop) audio=$(systemctl is-active zynq-audio)"

echo
echo "【2】★ 先停掉温度守护（否则它可能在关机过程中捣乱）"
sudo systemctl stop thermal-guard
sleep 1

echo
echo "【3】设 RTC 闹钟 = 现在 + 180 秒"
WAKE=$(( $(date +%s) + 180 ))
echo "$WAKE" | sudo tee /sys/class/rtc/rtc0/wakealarm >/dev/null
echo "  写入 $WAKE  ($(date -d @$WAKE '+%H:%M:%S'))"
echo "  读回: $(cat /sys/class/rtc/rtc0/wakealarm)"
sudo cat /proc/driver/rtc | grep -E "alrm_|alarm_"

echo
echo "【4】★ 3 秒后关机（poweroff）—— 之后就看板子能不能自己醒过来"
sync
sleep 3
sudo poweroff

# 如果还能执行到这里，说明 poweroff 没生效
echo
echo "  ⚠️ poweroff 命令返回了但系统还在跑（可能是 halt 不是 poweroff）"
