#!/bin/bash
echo "=== [1] WiFi 网卡 ==="
ls /sys/class/net/
for i in $(ls /sys/class/net/ | grep -E '^wl'); do
    echo "  无线网卡: $i"
    echo -n "    状态: "; cat /sys/class/net/$i/operstate 2>/dev/null
done
echo -n "  当前 IP: "; hostname -I | awk '{print $1}'

echo ""
echo "=== [2] WiFi 工具链 (决定怎么实现选择器) ==="
for t in iw iwlist wpa_cli wpa_supplicant nmcli rfkill; do
    p=$(command -v $t 2>/dev/null)
    if [ -n "$p" ]; then echo "  ✅ $t -> $p"; else echo "  ❌ $t 不可用"; fi
done

echo ""
echo "=== [3] wpa_supplicant 配置文件 ==="
ls -la /etc/wpa_supplicant/ 2>/dev/null | head -8
echo "  --- 内容 ---"
sudo cat /etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null | head -30 || echo "  (读不到)"

echo ""
echo "=== [4] 网络接口配置 ==="
ls /etc/network/interfaces.d/ 2>/dev/null
echo "  --- /etc/network/interfaces ---"
cat /etc/network/interfaces 2>/dev/null | head -20

echo ""
echo "=== [5] 当前连接的网络 ==="
cat /proc/net/wireless 2>/dev/null
sudo iw dev 2>/dev/null | head -12
echo "  --- 自动连接服务 ---"
systemctl list-units --type=service --all 2>/dev/null | grep -i -E "wifi|wpa|aic" | head -6

echo ""
echo "=== [6] 桌面应用清单 (选择器要挂进去) ==="
ls /home/zynq/ui/apps_*.py 2>/dev/null
echo -n "  桌面 app 注册处: "; grep -l "apps_net\|APPS" /home/zynq/ui/desktop.py 2>/dev/null
echo DONE-WIFI-DIAG
