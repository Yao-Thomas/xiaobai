#!/bin/bash
echo "=== [1] 服务文件是否存在 ==="
ls -l /etc/systemd/system/zynq-desktop.service 2>&1
echo ""
echo "=== [2] 是否已启用 ==="
ls -l /etc/systemd/system/multi-user.target.wants/zynq-desktop.service 2>&1
echo ""
echo "=== [3] 服务状态 ==="
systemctl status zynq-desktop.service --no-pager 2>&1 | head -20
echo ""
echo "=== [4] 服务日志 ==="
journalctl -u zynq-desktop.service --no-pager 2>&1 | tail -25
echo ""
echo "=== [5] 直接跑一下看报错 ==="
cd /home/zynq/ui
timeout 6 python3 -u desktop.py 2>&1 | head -20
echo "退出码: $?"
echo ""
echo "=== [6] 文件检查 ==="
ls -l /home/zynq/ui/
