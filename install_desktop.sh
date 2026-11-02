#!/bin/bash
# 给板子装桌面环境 —— X 服务器 + LXDE
export DEBIAN_FRONTEND=noninteractive
echo "############ [1/4] apt update ############"
apt-get update -qq 2>&1 | tail -3

echo ""
echo "############ [2/4] 装 X 服务器 + 视频/触摸驱动 ############"
apt-get install -y --no-install-recommends \
  xserver-xorg xserver-xorg-core xserver-xorg-video-fbdev \
  xserver-xorg-input-libinput xserver-xorg-input-evdev \
  xinit x11-xserver-utils xauth x11-apps xterm 2>&1 | tail -8

echo ""
echo "############ [3/4] 装 LXDE 桌面 + 中文字体 ############"
apt-get install -y --no-install-recommends \
  lxde-core lxde-icon-theme lxterminal pcmanfm \
  fonts-dejavu-core fonts-wqy-zenhei dbus-x11 xvkbd 2>&1 | tail -8

echo ""
echo "############ [4/4] 校验 ############"
for c in startx Xorg xinit openbox lxpanel pcmanfm lxterminal; do
  printf "%-12s -> %s\n" "$c" "$(command -v $c || echo '缺失!')"
done
echo -n "已安装包数: "; dpkg -l | grep -c '^ii'
echo -n "磁盘占用: "; df -h / | tail -1
echo "DESKTOP_INSTALL_DONE"
