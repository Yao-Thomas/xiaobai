#!/bin/sh
# deploy_all.sh —— 上电后一键部署（在板子上以 root 跑）
#
# 装上今天做的全部东西，并跑一遍验证：
#   1. 温度保护（守护 + 开机冷却暂停）
#   2. 硬件工具集（12 个工具注册进 agent）
#   3. 声学自测脚本
#   4. 变更管理（变更单 + 自动验证 + 自动回滚）
#   5. 离线测试 + 硬件回归
#
# 用法（从 PC 侧）：
#   python board.py -p <各文件> ...
#   python board.py -f deploy_all.sh

set +e

echo "======================================================"
echo " 一键部署 —— 系统管家小白"
echo "======================================================"
date
echo

echo "【0】环境检查"
for d in /home/zynq /home/zynq/agent; do
  printf "  %-22s %s\n" "$d" "$([ -d $d ] && echo 存在 || echo '★ 缺失')"
done
echo "  当前温度: $(/usr/bin/python3 /home/zynq/thermal_guard.py --once 2>/dev/null || echo 读不到) °C"
echo

echo "【1】语法检查"
for f in /home/zynq/thermal_guard.py /home/zynq/cool_down.py \
         /home/zynq/acoustic_selftest.py \
         /home/zynq/agent/hw_tools.py /home/zynq/agent/hw_change.py; do
  if [ -f "$f" ]; then
    if /usr/bin/python3 -c "import ast,io,sys; ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" "$f" 2>/dev/null; then
      echo "  ✓ $f"
    else
      echo "  ✗ $f  语法错误！"
    fi
  else
    echo "  - $f  不存在（跳过）"
  fi
done
echo

echo "【2】持久目录（★ 不能用 /run —— tmpfs，重启就丢）"
sudo mkdir -p /var/lib/thermal /var/lib/hwchange
sudo chmod 755 /var/lib/thermal /var/lib/hwchange
echo "  ✓ /var/lib/thermal  /var/lib/hwchange"
echo

echo "【3】装 service"
for u in thermal-guard thermal-cooldown; do
  if [ -f "/tmp/$u.service" ]; then
    sudo cp "/tmp/$u.service" /etc/systemd/system/
    echo "  ✓ 装了 $u.service"
  else
    echo "  - /tmp/$u.service 不在，跳过"
  fi
done
sudo systemctl daemon-reload
sudo systemctl enable thermal-guard thermal-cooldown 2>&1 | tail -3
echo

echo "【4】起服务"
sudo systemctl restart thermal-guard
sudo systemctl start thermal-cooldown
sleep 6
for s in thermal-guard thermal-cooldown zynq-desktop zynq-audio zynq-agent; do
  printf "  %-20s %s\n" "$s" "$(systemctl is-active $s)"
done
echo

echo "【4b】★ 装云协同服务"
if [ -f /home/zynq/install_cloud_api.sh ]; then
  sudo sh /home/zynq/install_cloud_api.sh 2>&1 | tail -28
else
  echo "  - install_cloud_api.sh 不在，跳过"
fi
echo

echo "【4c】★ 桌面文件（变更历史 App）"
# apps_hwchange.py 是新应用，桌面打开应用时会 importlib.reload，传上去就能用
if [ -f /home/zynq/ui/apps_hwchange.py ]; then
  echo "  ✓ apps_hwchange.py 已就位"
else
  echo "  - apps_hwchange.py 不在"
fi
# desktop.py 改了 APPS 表（加了"变更历史"），★ 要换文件 + 重启桌面
if [ -f /tmp/desktop.py.new ]; then
  TS=$(date +%Y%m%d_%H%M%S)
  if [ -f /home/zynq/ui/desktop.py ]; then
    sudo cp /home/zynq/ui/desktop.py "/home/zynq/ui/desktop.py.bak_$TS"
    echo "  已备份 desktop.py -> desktop.py.bak_$TS"
  fi
  # ★ 换之前先做语法检查，语法错会让桌面起不来
  if /usr/bin/python3 -c "import ast,io,sys; ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" /tmp/desktop.py.new 2>/dev/null; then
    sudo cp /tmp/desktop.py.new /home/zynq/ui/desktop.py
    sudo chown zynq:zynq /home/zynq/ui/desktop.py
    sudo systemctl restart zynq-desktop
    sleep 6
    echo "  zynq-desktop: $(systemctl is-active zynq-desktop)"
  else
    echo "  ★ /tmp/desktop.py.new 语法错，不换（桌面保持原样）"
  fi
else
  echo "  - /tmp/desktop.py.new 不在，跳过"
fi
echo

echo "【5】温度状态"
sudo /usr/bin/python3 /home/zynq/thermal_guard.py --status
echo

echo "【6】★ 离线测试（不需要板子硬件）"
cd /home/zynq
for t in test_hw_tools.py test_hw_change.py test_selftest_math.py \
         test_fpga_loop.py test_cloud_api_http.py test_hwchange_ui.py; do
  if [ -f "$t" ]; then
    out=$(/usr/bin/python3 "$t" 2>&1 | tail -2 | tr '\n' ' ')
    printf "  %-26s %s\n" "$t" "$out"
  else
    printf "  %-26s (不存在)\n" "$t"
  fi
done
echo

echo "【6b】★ 分级推理自测"
/usr/bin/python3 /home/zynq/agent/tiers.py --selftest 2>&1 | tail -2
echo

echo "【6c】★ 云协同自检"
/usr/bin/python3 /home/zynq/cloud_api.py --selftest 2>&1 | tail -2
echo

echo "【7】★ 硬件回归检查"
if [ -f /home/zynq/agent/hw_change.py ]; then
  cd /home/zynq && sudo /usr/bin/python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
from agent import hw_change as HC
ok, checks = HC.verify_all(verbose=True)
print()
print('结论:', '全部通过' if ok else '★ 有硬检查失败')
" 2>&1 | tail -25
else
  echo "  (hw_change.py 不在)"
fi
echo

echo "【8】agent 工具数确认"
if curl -s --max-time 8 http://127.0.0.1:8765/tools >/tmp/_tools.json 2>/dev/null; then
  /usr/bin/python3 -c "
import json
d = json.load(open('/tmp/_tools.json'))
names = [t.get('name') if isinstance(t,dict) else str(t) for t in d.get('tools',[])]
print('  工具数 =', len(names))
hw = [n for n in names if n.startswith('hw_')]
print('  硬件工具 (%d): %s' % (len(hw), ', '.join(sorted(hw))))
" 2>&1
else
  echo "  agent HTTP 没响应 —— zynq-agent 在跑吗？"
fi
echo

echo "======================================================"
echo " 部署完成"
echo "======================================================"
echo " 接下来可以："
echo "   ① 声学自测:  sudo python3 /home/zynq/acoustic_selftest.py"
echo "   ② 看温度:    sudo python3 /home/zynq/thermal_guard.py --status"
echo "   ③ 变更单:    sudo python3 /home/zynq/agent/hw_change.py --list"
