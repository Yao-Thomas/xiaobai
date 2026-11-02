#!/bin/bash
#=====================================================================
#  clean_dup_wifi.sh —— 清理重复的 WiFi 配置 + 自动连接脚本
#  现象: list_networks 里出现多条同名条目 (旧版 connect() 每次都新建)
#=====================================================================
set -u
IF=wlx688fc92bd646

echo "=== [1] 清理前的列表 ==="
wpa_cli -i $IF list_networks

echo ""
echo "=== [2] 删除所有 DISABLED 的重复条目 ==="
# 保留 CURRENT 的那条, 其余同名/禁用的都删掉
wpa_cli -i $IF list_networks | tail -n +2 | while read -r line; do
    nid=$(echo "$line" | cut -f1)
    ssid=$(echo "$line" | cut -f2)
    flags=$(echo "$line" | grep -o '\[.*\]')
    case "$nid" in
        ''|*[!0-9]*) continue ;;
    esac
    if echo "$flags" | grep -q "CURRENT"; then
        echo "  保留 id=$nid ($ssid) [当前连接]"
        continue
    fi
    echo "  删除 id=$nid ($ssid) $flags"
    wpa_cli -i $IF remove_network "$nid" >/dev/null
done

echo ""
echo "=== [3] 保存配置 ==="
wpa_cli -i $IF save_config

echo ""
echo "=== [4] 清理后的列表 ==="
wpa_cli -i $IF list_networks

echo ""
echo "=== [5] 确认网络还在 (不能弄断) ==="
sleep 3
echo -n "  SSID: "; iwconfig $IF 2>/dev/null | grep -oP 'ESSID:\S+'
echo -n "  IP:   "; hostname -I | awk '{print $1}'

echo ""
echo "=== [6] 看一眼配置文件 ==="
cat /etc/wpa_supplicant/wpa_supplicant.conf
echo DONE-CLEAN
