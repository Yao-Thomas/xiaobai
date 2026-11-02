#!/usr/bin/env bash
echo "=== 1) desktop.py 里跟「开始 / 全部应用」有关的代码 ==="
grep -n "全部应用\|开始\|start_menu\|show_menu\|menu_open\|ALL_APPS\|all_apps" /home/zynq/ui/desktop.py | head -30 | sed 's/^/  /'
echo
echo "=== 2) 底部 Dock 是怎么画的 ==="
grep -n "def.*dock\|dock" /home/zynq/ui/desktop.py | head -20 | sed 's/^/  /'
echo
echo "=== 3) fbui 里 dock 相关的绘制 ==="
grep -n "def dock\|def build_static\|全部应用" /home/zynq/ui/fbui.py /home/zynq/ui/home.py 2>/dev/null | head -20 | sed 's/^/  /'
