#!/bin/bash
# 配置 X 服务器(fbdev + 触摸) + LXDE 自启
echo "############ [1] 写 /etc/X11/xorg.conf ############"
cat > /etc/X11/xorg.conf <<'EOF'
Section "ServerLayout"
    Identifier "Layout0"
    Screen 0 "Screen0"
EndSection

Section "Device"
    Identifier  "Card0"
    Driver      "fbdev"
    Option      "fbdev" "/dev/fb0"
EndSection

Section "Monitor"
    Identifier  "Monitor0"
    HorizSync   30-70
    VertRefresh 50-75
EndSection

Section "Screen"
    Identifier  "Screen0"
    Device      "Card0"
    Monitor     "Monitor0"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
    EndSubSection
EndSection

Section "InputClass"
    Identifier          "touchscreen"
    MatchIsTouchscreen  "on"
    Driver              "libinput"
    Option              "AccelProfile" "none"
EndSection
EOF
cat /etc/X11/xorg.conf | head -12

echo ""
echo "############ [2] 用户 .xinitrc (进 LXDE) ############"
cat > /home/zynq/.xinitrc <<'EOF'
#!/bin/sh
# 关掉屏幕保护/DPMS(触摸用)
xset s off
xset -dpms
xset s noblank
# 关掉鼠标加速(触摸更准)
xset m 0 0
exec startlxde
EOF
chmod +x /home/zynq/.xinitrc
chown zynq:zynq /home/zynq/.xinitrc
cat /home/zynq/.xinitrc

echo ""
echo "############ [3] 静音内核日志(免得刷屏) ############"
echo "1 4 1 7" > /proc/sys/kernel/printk
cat /proc/sys/kernel/printk

echo ""
echo "############ [4] 测试 X 能否起来(独立 Xorg, 不带桌面) ############"
pkill -9 Xorg 2>/dev/null
sleep 2
nohup Xorg :0 -config /etc/X11/xorg.conf > /tmp/xorg.log 2>&1 &
sleep 12
echo "--- xorg.log 关键行 ---"
grep -iE "error|fail|fatal|\(EE\)|Using|fbdev|screen|depth|libinput|touch" /tmp/xorg.log | head -25
echo "--- X 进程 ---"
pgrep -af Xorg || echo "(X 没起来!)"
echo ""
echo "--- 用 xdpyinfo 看分辨率 ---"
DISPLAY=:0 xdpyinfo 2>/dev/null | grep -E "dimensions|depth of root" || echo "(xdpyinfo 不可用)"
echo "SETUP_X_DONE"
