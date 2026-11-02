#!/bin/bash
# 逐个尝试 X 配置，抓完整错误
try() {
  local name="$1"; local conf="$2"
  echo "################ 尝试: $name ################"
  cat > /etc/X11/xorg.conf <<EOF
$conf
EOF
  pkill -9 Xorg 2>/dev/null; sleep 2
  rm -f /tmp/x_$name.log
  nohup Xorg :0 -config /etc/X11/xorg.conf -logfile /tmp/x_$name.log > /dev/null 2>&1 &
  sleep 12
  if pgrep -f "Xorg :0" > /dev/null; then
    echo ">>> ✅ 成功! X 在运行"
    DISPLAY=:0 xrandr 2>/dev/null | head -4
    pkill -9 Xorg; sleep 2
    return 0
  fi
  echo ">>> ❌ 失败, 日志关键部分:"
  grep -vE "^\s*$" /tmp/x_$name.log 2>/dev/null | tail -30
  echo ""
  return 1
}

CONF_FBDEV='
Section "ServerLayout"
    Identifier "L"
    Screen 0 "S0"
EndSection
Section "Device"
    Identifier "D0"
    Driver "fbdev"
    Option "fbdev" "/dev/fb0"
EndSection
Section "Monitor"
    Identifier "M0"
EndSection
Section "Screen"
    Identifier "S0"
    Device "D0"
    Monitor "M0"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
    EndSubSection
EndSection
'

CONF_FBDEV_SHADOW='
Section "ServerLayout"
    Identifier "L"
    Screen 0 "S0"
EndSection
Section "Device"
    Identifier "D0"
    Driver "fbdev"
    Option "fbdev" "/dev/fb0"
    Option "ShadowFB" "true"
EndSection
Section "Monitor"
    Identifier "M0"
EndSection
Section "Screen"
    Identifier "S0"
    Device "D0"
    Monitor "M0"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
    EndSubSection
EndSection
'

CONF_MODESET1='
Section "ServerLayout"
    Identifier "L"
    Screen 0 "S0"
EndSection
Section "Device"
    Identifier "D0"
    Driver "modesetting"
    Option "kmsdev" "/dev/dri/card0"
    Option "AccelMethod" "none"
    Option "SWcursor" "true"
EndSection
Section "Monitor"
    Identifier "M0"
EndSection
Section "Screen"
    Identifier "S0"
    Device "D0"
    Monitor "M0"
    DefaultDepth 24
EndSection
'

try fbdev "$CONF_FBDEV"
echo ""
try shadow "$CONF_FBDEV_SHADOW"
echo ""
try modeset "$CONF_MODESET1"
echo ""
echo "=== 额外信息: Xorg 支持的驱动 ==="
Xorg -version 2>&1 | head -3
ls -l /dev/dri/card0 /dev/fb0
echo ALL_TRIED
