#!/bin/sh
# diag_cloud_svc.sh —— 查云协同服务为什么退出
echo "======================================================"
echo " 云协同服务诊断"
echo "======================================================"
echo
echo "【1】服务属性"
systemctl show cloud-api -p Restart -p RestartUSec -p ExecMainStatus \
  -p ExecMainCode -p NRestarts -p Result -p ActiveState -p SubState 2>/dev/null
echo
echo "【2】手动前台跑 5 秒，看会不会退"
echo "  （先停服务，避免抢 8768 端口）"
sudo systemctl stop cloud-api 2>/dev/null
sleep 1
echo "  --- 前台跑（超时 6 秒）---"
sudo timeout 6 /usr/bin/python3 -u /home/zynq/cloud_api.py --no-discover 2>&1 | head -20
echo "  退出码: $?"
echo
echo "【3】端口占着没"
ss -tlnp 2>/dev/null | grep 8768 || echo "  8768 没被占"
echo
echo "【4】配置和目录"
ls -la /etc/xiaobai-cloud.json 2>/dev/null
sudo ls -la /var/lib/xiaobai-cloud/ 2>/dev/null
echo
echo "【5】重启服务并观察 15 秒"
sudo systemctl start cloud-api
for i in 1 2 3 4 5; do
  sleep 3
  printf "  +%2d 秒: %s" $((i*3)) "$(systemctl is-active cloud-api)"
  if systemctl is-active --quiet cloud-api; then
    printf "  (PID %s)\n" "$(systemctl show cloud-api -p MainPID --value)"
  else
    printf "  ★ 挂了\n"
  fi
done
echo
echo "【6】如果又挂了，看最后报错"
if ! systemctl is-active --quiet cloud-api; then
  echo "  --- journal ---"
  sudo journalctl -u cloud-api -n 15 --no-pager 2>/dev/null | tail -15
  echo "  --- 日志文件尾 ---"
  tail -10 /var/log/cloud_api.log 2>/dev/null
fi
