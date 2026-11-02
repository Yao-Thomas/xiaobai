#!/bin/bash
echo "=== [1] 桌面日志 (找报错) ==="
tail -40 /var/log/zynq-desktop.log

echo ""
echo "=== [2] 测试只读函数 (不碰连接, 避免切网) ==="
cd /home/zynq/ui
python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
import apps_wifi as W
print('  wlan_name():', W.iface())
print('  current_ssid():', repr(W.current_ssid()))
print('  has_ip():', W.has_ip())
print('  list_networks():')
try:
    s = W.list_networks()
    for k,v in s.items():
        print('     %r -> id %s' % (k, v))
except Exception as e:
    import traceback; traceback.print_exc()
print('  bars(None):', W.bars(None))
print('  bars(-55):', W.bars(-55))
"

echo ""
echo "=== [3] wpa_cli list_networks 原始输出 ==="
wpa_cli -i wlx688fc92bd646 list_networks 2>&1 | cat -A | head -8

echo ""
echo "=== [4] 测试 connect_saved 的构造 (不执行) ==="
python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
import apps_wifi as W
import inspect
src = inspect.getsource(W.connect_saved)
print(src[:600])
"
echo DONE-DEBUG
