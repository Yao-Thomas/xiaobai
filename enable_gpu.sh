#!/bin/bash
#=====================================================================
#  enable_gpu.sh —— bitstream 已加载好, 这里只做"启用桌面加速"
#=====================================================================
set -u

echo "=== [1] 确认 GPU 在 ==="
cd /home/zynq/ui
python3 - <<'EOF'
import sys
sys.path.insert(0, "/home/zynq/ui")
from gpu import GPU
g = GPU(0x43CB0000, verbose=False)
ok = g.probe()
print("  GPU:", "存在 ✅" if ok else "无响应 ❌")
sys.exit(0 if ok else 1)
EOF
if [ $? -ne 0 ]; then
    echo "❌ GPU 不在, 不写标记(避免桌面崩溃)"
    exit 1
fi

echo ""
echo "=== [2] 写入 GPU 标记 ==="
echo "0x43CB0000" > /home/zynq/.gpu_addr
chown zynq:zynq /home/zynq/.gpu_addr 2>/dev/null
echo "  /home/zynq/.gpu_addr = $(cat /home/zynq/.gpu_addr)"

echo ""
echo "=== [3] 重启桌面 ==="
systemctl restart zynq-desktop
sleep 12
echo -n "  服务: "; systemctl is-active zynq-desktop
echo "  --- 日志 ---"
tail -6 /var/log/zynq-desktop.log | sed 's/^/    /'

echo ""
echo "=== [4] 确认显存物理地址 ==="
echo -n "  "; cat /home/zynq/.fb_phys 2>/dev/null || echo "(无)"

echo ""
echo "=== [5] 跑 GPU 演示 (会直接在屏幕上画东西) ==="
python3 /home/zynq/ui/gpu_demo.py 2>&1 | sed 's/^/  /'

echo ""
echo "=== DONE ==="
