cd /home/zynq/ui
echo "=== 用 App 自己的函数测（不改变连接）==="
python3 - <<'PYEOF'
import sys
sys.path.insert(0, '/home/zynq/ui')
import apps_wifi as w

print("网卡名       :", w.iface())
print("list_networks:", w.list_networks())
print("current_ssid :", w.current_ssid())
print("has_ip       :", repr(w.has_ip()))
print("conf_has(13A02):", w.conf_has("13A02"))
print()
print("--- 试 save_config（App 的调用方式）---")
ok, out = w.wpa("save_config", 8)
print("  wpa save_config ->", ok, repr(out.strip()[:60]))
print("  conf_has(13A02) 之后:", w.conf_has("13A02"))
print()
print("--- wpa_cli 是否可用（App 依赖它）---")
print("  have(wpa_cli) :", w.have("wpa_cli"))
print("  have(networkctl):", w.have("networkctl"))
print("  have(iw)      :", w.have("iw"))
print()
print("--- 权限：当前用户 ---")
import os
print("  euid:", os.geteuid(), " is_root:", w.is_root())
PYEOF