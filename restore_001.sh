#!/bin/bash
#=====================================================================
#  restore_001.sh —— 把 001 网络加回配置, 并设置优先级
#  重要: 只 add/set/enable + save_config, 【绝不 select_network】
#        否则会立刻切换网络, 我就失去连接了
#=====================================================================
set -u
IF=wlx688fc92bd646

echo "=== [1] 当前状态 ==="
wpa_cli -i $IF list_networks
echo -n "  当前 SSID: "; iwconfig $IF 2>/dev/null | grep -oP 'ESSID:\S+'

echo ""
echo "=== [2] 检查 001 在不在 ==="
if wpa_cli -i $IF list_networks | grep -qP '\t001\t'; then
    echo "  001 已在配置里, 只调整优先级"
else
    echo "  001 不在, 添加它"
    NID=$(wpa_cli -i $IF add_network | tail -1)
    echo "  新 network id = $NID"
    wpa_cli -i $IF set_network $NID ssid '"001"'
    wpa_cli -i $IF set_network $NID psk '"yaoenqi127"'
    # 不要 select / enable 之外的动作, 避免立刻切换
    wpa_cli -i $IF enable_network $NID
fi

echo ""
echo "=== [3] 设置优先级 (让学校网优先, 001 作为备用) ==="
# 001 -> priority 1 ; CMCC-Y2Ss -> priority 2
wpa_cli -i $IF list_networks | tail -n +2 | while read -r line; do
    nid=$(echo "$line" | cut -f1)
    ssid=$(echo "$line" | cut -f2)
    case "$nid" in ''|*[!0-9]*) continue ;; esac
    case "$ssid" in
        001)        wpa_cli -i $IF set_network "$nid" priority 1 >/dev/null
                    echo "  id=$nid ($ssid) -> priority 1" ;;
        CMCC-Y2Ss)  wpa_cli -i $IF set_network "$nid" priority 2 >/dev/null
                    echo "  id=$nid ($ssid) -> priority 2 (优先)" ;;
        *)          echo "  id=$nid ($ssid) 保持不变" ;;
    esac
done

echo ""
echo "=== [4] 保存 ==="
wpa_cli -i $IF save_config

echo ""
echo "=== [5] 确认网络没断 ==="
sleep 3
echo -n "  SSID: "; iwconfig $IF 2>/dev/null | grep -oP 'ESSID:\S+'
echo -n "  IP:   "; hostname -I | awk '{print $1}'

echo ""
echo "=== [6] 最终配置 ==="
wpa_cli -i $IF list_networks
echo "  --- 配置文件 ---"
cat /etc/wpa_supplicant/wpa_supplicant.conf
echo DONE-RESTORE
