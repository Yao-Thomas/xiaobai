#!/bin/bash
#=====================================================================
#  install_guard.sh —— 安装黑屏安全网
#=====================================================================
set -u
echo "=== [1] 放好脚本 ==="
ls -la /home/zynq/ui/screen_guard.py
chmod +x /home/zynq/ui/screen_guard.py

echo ""
echo "=== [2] 安装 systemd 服务 ==="
cat > /etc/systemd/system/zynq-screen-guard.service <<'UNIT'
[Unit]
Description=Zynq black-screen watchdog and auto-recovery
After=zynq-desktop.service
Wants=zynq-desktop.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -u /home/zynq/ui/screen_guard.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/zynq-screen-guard.log
StandardError=append:/var/log/zynq-screen-guard.log

[Install]
WantedBy=multi-user.target
UNIT
echo "  已安装"

echo ""
echo "=== [3] 启用 + 启动 ==="
systemctl daemon-reload
systemctl enable zynq-screen-guard.service 2>&1 | tail -1
# 清掉上次的重启计数
rm -f /home/zynq/.guard_reboot_count
systemctl restart zynq-screen-guard.service
sleep 12
echo -n "  服务: "; systemctl is-active zynq-screen-guard

echo ""
echo "=== [4] 看它采样到了什么 (验证不会误判) ==="
sleep 40
tail -8 /var/log/zynq-screen-guard.log

echo ""
echo "=== [5] 手动采样一次当前屏幕 ==="
python3 -c "
import mmap, os
FB='/dev/fb0'; W,H,S=1024,600,3072
fd=os.open(FB,os.O_RDONLY)
mm=mmap.mmap(fd,S*H,mmap.MAP_SHARED,mmap.PROT_READ)
dark=0;n=0;tot=0
for y in range(5,H,23):
    for x in range(5,W,29):
        o=y*S+x*3
        s=mm[o]+mm[o+1]+mm[o+2]
        tot+=s
        if s<24: dark+=1
        n+=1
mm.close();os.close(fd)
print('  采样点 %d 个, 黑点 %d 个 (%.1f%%), 平均亮度 %.0f' % (n,dark,dark*100.0/n,tot*100.0/n))
print('  判定:', '黑屏!' if dark*1.0/n>0.85 else '正常 ✅ (不会误触发)')
"

echo ""
echo "=== [6] 暂停开关说明 ==="
echo "  暂停:  touch /home/zynq/.guard_pause"
echo "  恢复:  rm /home/zynq/.guard_pause"
echo DONE-GUARD
