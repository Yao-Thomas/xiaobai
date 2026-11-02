#!/bin/bash
echo "=== 1. 探测 GPU @0x43CB0000 ==="
cd /home/zynq/ui
python3 - <<'EOF'
import sys
sys.path.insert(0, "/home/zynq/ui")
from gpu import GPU
g = GPU(0x43CB0000, verbose=False)
ok = g.probe()
print("  探测结果:", "存在 ✅" if ok else "无响应 ❌")
for n, o in (("CTRL",0),("OP",4),("BASE",8),("STRIDE",0xC),
             ("XY0",0x10),("XY1",0x14),("COLOR",0x18),("PIXCNT",0x1C),("STATUS",0x20)):
    print("  %-8s = 0x%08X" % (n, g.rd(o)))
g.close()
EOF

echo ""
echo "=== 2. 读取显存物理地址 ==="
cat /home/zynq/.fb_phys 2>/dev/null || echo "  (无)"

echo ""
echo "=== 3. dmesg ==="
dmesg | tail -4

echo ""
echo "=== 4. 桌面服务 ==="
systemctl is-active zynq-desktop
echo DONE
