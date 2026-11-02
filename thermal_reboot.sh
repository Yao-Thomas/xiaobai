#!/bin/sh
# thermal_reboot.sh —— 按用户要求主动重启散热
#
# 背景（用户原话）：
#   "它温度不会超过90度的，你反正到80多度运行个20分钟以后
#     你就重关机一段时间重启一次。"
#
# ★ 只允许 systemctl reboot，绝不允许 poweroff ——
#   这块板子的 poweroff 是【单向操作】（实测过：RTC 闹钟唤不醒，
#   串口控制线也没接，一旦 poweroff 就只能 physical 断电）。
#
# 这个脚本做三件事：
#   ① 记录重启原因和当前温度（留证据）
#   ② 写冷却标记 —— 开机后 cool_down.py 会读它，先歇 N 分钟再干活
#   ③ reboot

echo "======================================================"
echo " 主动重启散热"
echo "======================================================"
echo
T=$(sudo /usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null || echo "?")
echo "  重启前温度: ${T} °C"
date '+  时间: %Y-%m-%d %H:%M:%S'
uptime | sed 's/^ *//' | sed 's/^/  /'
echo

echo "  ① 记录原因"
# ★ 这个脚本可能不是以 root 跑的（board.py 上传后普通用户执行），
#   而 /var/lib/thermal 属 root —— 直接 >> 会 Permission denied。
#   所以用 sudo tee -a，而且失败也不影响后面的重启。
{
  echo "$(date '+%Y-%m-%d %H:%M:%S') 主动重启散热（温度 ${T}，用户要求 80+ 待一段就重启）"
} | sudo tee -a /var/lib/thermal/reboot_log.txt > /dev/null 2>&1 || \
  echo "    （日志写不进去，不影响重启）"
sudo tail -3 /var/lib/thermal/reboot_log.txt 2>/dev/null | sed 's/^/    /'
echo

echo "  ② 写冷却标记（开机后 cool_down.py 会先歇一会儿）"
# ★ 必须放 /var/lib —— /run 是 tmpfs，重启就丢
sudo touch /var/lib/thermal/cool_down
ls -la /var/lib/thermal/cool_down | sed 's/^/    /'
echo

echo "  ③ 重启（不是关机！）"
echo "     ★ poweroff 在这块板上是单向操作，绝对不能用来'散热'"
sync
echo "     正在重启…（大约 30~40 秒后回来）"
sudo systemctl reboot
