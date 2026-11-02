echo "=== 1) 在 wifi-connect.service 里加"关省电 + 补 DHCP" ==="
sudo cp /etc/systemd/system/wifi-connect.service /etc/systemd/system/wifi-connect.service.bak_netfix

# 在 ExecStartPost 之后插入两步：关省电、强制 renew
sudo python3 - <<'PYEOF'
p = "/etc/systemd/system/wifi-connect.service"
src = open(p, encoding="utf-8").read()

# 如果已经改过就不重复
if "power_save off" in src:
    print("  已经改过，跳过")
else:
    add = (
        "# ★ 2026-10-01 修复：关掉 WiFi 省电 + 主动 renew DHCP\n"
        "#   省电开着时网卡空闲会休眠 -> AP 认为掉线 -> Lost carrier\n"
        "#   实测开机 13 分钟掉了 40 次。\n"
        "ExecStartPost=-/bin/sh -c 'IF=$(ls /sys/class/net | grep ^wl | head -1); "
        "/usr/sbin/iw dev $IF set power_save off 2>/dev/null; "
        "/usr/bin/networkctl reconfigure $IF 2>/dev/null; true'\n"
    )
    # 插到最后一个 ExecStartPost /sleep 6 之后
    marker = "ExecStartPost=/bin/sleep 6\n"
    if marker in src:
        src = src.replace(marker, marker + add, 1)
    else:
        src = src.rstrip() + "\n" + add
    open(p, "w", encoding="utf-8").write(src)
    print("  已插入修复步骤")
PYEOF

echo
echo "=== 2) 改后的 service ==="
sudo cat /etc/systemd/system/wifi-connect.service
echo
echo "=== 3) 重载 systemd ==="
sudo systemctl daemon-reload && echo "  daemon-reload OK"