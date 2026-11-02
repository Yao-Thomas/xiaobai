cd /home/zynq/ui
echo "=== 用 App 的函数测「断开 -> 重连」全流程 ==="
python3 - <<'PYEOF'
import sys, time
sys.path.insert(0, '/home/zynq/ui')
import apps_wifi as w

print("【1】当前状态")
print("   ssid      :", w.current_ssid())
print("   有 IP     :", repr(w.has_ip()))
print("   已保存列表:", w.list_networks())

print()
print("【2】断开")
w.disconnect()
time.sleep(3)
print("   ssid      :", repr(w.current_ssid()))
print("   有 IP     :", repr(w.has_ip()))

print()
print("【3】重连（走 connect_saved，和换网络用的同一套）")
saved = w.list_networks()
nid = saved.get("13A02")
print("   13A02 的 network id:", nid)
t0 = time.time()
ok, msg = w.connect_saved("13A02", nid, wait=40)
print("   结果: ok=%s  msg=%s  耗时=%.1fs" % (ok, msg, time.time()-t0))
print("   ssid      :", w.current_ssid())
print("   有 IP     :", repr(w.has_ip()))
PYEOF