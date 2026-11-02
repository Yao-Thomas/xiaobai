#!/bin/bash
rm -rf /home/zynq/ui/__pycache__
rm -f /home/zynq/.desktop_order
systemctl restart zynq-desktop
sleep 12
echo -n "服务: "; systemctl is-active zynq-desktop

echo ""
echo "--- 网络信息解析测试 ---"
cd /home/zynq/ui
python3 - <<'EOF'
import apps_net as n
w, ip, gw, mac, ssid, sig = n.net_info()
print("  网卡=%s  IP=%s  网关=%s" % (w, ip, gw))
print("  MAC=%s  SSID=[%s]  信号=%s" % (mac, ssid, sig))
EOF

echo ""
echo "--- 系统信息计算测试 ---"
python3 - <<'EOF'
import os, platform
st = os.statvfs("/")
t = st.f_blocks * st.f_frsize // (1024*1024)
f = st.f_bavail * st.f_frsize // (1024*1024)
u = t - f
print("  磁盘: 已用 %.1fG / 总 %.1fG (%d%%)" % (u/1024.0, t/1024.0, 100*u//t))
EOF
echo DONE
