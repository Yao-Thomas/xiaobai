#!/bin/sh
# deploy_thermal.sh —— 上电后一键部署温度保护（在板子上以 root 跑）
#
# 装两样东西：
#   1. thermal-guard.service   温度守护（分级降载 + 96°C 重启冷却）
#   2. thermal-cooldown.service 开机冷却暂停（重启后先凉一会儿再起桌面）
#
# ★ 关键教训（已写进代码注释）：
#   这块板子 poweroff 之后是 halt —— 电源还在、串口静默、RTC 闹钟叫不醒、
#   DTR/RTS 也复位不了。poweroff 是【单向】的，只能人工按键/重新上电。
#   所以守护里绝对不能用 poweroff，只能用 reboot。

set -e

echo "======================================================"
echo " 部署温度保护"
echo "======================================================"

echo
echo "【1】放好脚本"
ls -la /home/zynq/thermal_guard.py /home/zynq/cool_down.py
python3 -c "import ast,io; ast.parse(io.open('/home/zynq/thermal_guard.py',encoding='utf-8').read()); print('  thermal_guard.py 语法 OK')"
python3 -c "import ast,io; ast.parse(io.open('/home/zynq/cool_down.py',encoding='utf-8').read()); print('  cool_down.py 语法 OK')"

echo
echo "【2】建持久目录（★ 不能用 /run —— 那是 tmpfs，重启就丢）"
sudo mkdir -p /var/lib/thermal
sudo chmod 755 /var/lib/thermal

echo
echo "【3】装 service"
sudo cp /tmp/thermal-guard.service /etc/systemd/system/
sudo cp /tmp/thermal-cooldown.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable thermal-guard thermal-cooldown 2>&1 | tail -4

echo
echo "【4】起服务"
sudo systemctl restart thermal-guard
sudo systemctl start thermal-cooldown
sleep 6

echo
echo "【5】状态"
for s in thermal-guard thermal-cooldown; do
  printf "  %-20s %s\n" "$s" "$(systemctl is-active $s)"
done

echo
echo "【6】当前温度"
sudo python3 /home/zynq/thermal_guard.py --once

echo
echo "【7】守护状态文件"
sudo python3 /home/zynq/thermal_guard.py --status

echo
echo "【8】演练各等级（确认 96°C 是重启不是关机）"
for t in 89 91 93 97; do
  sudo python3 /home/zynq/thermal_guard.py --test $t | head -3
  echo
done

echo "======================================================"
echo " 完成"
echo "======================================================"
