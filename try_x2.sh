#!/bin/bash
echo "=== [1] 可用的 X 视频驱动 ==="
ls /usr/lib/xorg/modules/drivers/ 2>/dev/null

echo ""
echo "=== [2] 改用 modesetting 驱动 (走 DRM/KMS, card0=LCD) ==="
cat > /etc/X11/xorg.conf <<'EOF'
Section "ServerLayout"
    Identifier "Layout0"
    Screen 0 "Screen0"
EndSection

Section "Device"
    Identifier  "Card0"
    Driver      "modesetting"
    Option      "kmsdev" "/dev/dri/card0"
    Option      "AccelMethod" "none"
EndSection

Section "Monitor"
    Identifier  "Monitor0"
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
EndSection
EOF

echo ""
echo "=== [3] 启动测试 ==="
pkill -9 Xorg 2>/dev/null
sleep 2
nohup Xorg :0 -config /etc/X11/xorg.conf > /tmp/xorg2.log 2>&1 &
sleep 14
echo "--- 日志关键行 ---"
grep -iE "error|fail|fatal|\(EE\)|Using|modeset|depth|libinput|touch|output|screen" /tmp/xorg2.log | head -30
echo "--- X 进程 ---"
pgrep -af Xorg || echo "(X 没起来!)"
echo "--- 分辨率 ---"
DISPLAY=:0 xrandr 2>/dev/null | head -5 || echo "(xrandr 不可用)"
echo "TRY2_DONE"
