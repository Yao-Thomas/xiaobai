import json, sys, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BD = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs"
      r"\sources_1\bd\system\system.bd")
d = json.load(open(BD, encoding="utf-8", errors="replace"))
txt = json.dumps(d, ensure_ascii=False)

print("=== i2s_receiver 暴露了哪些端口 ===")
rx = d["design"]["components"]["audio"]["components"].get("i2s_receiver", {})
print("  组件键:", sorted(rx.keys()))
for k in ("ports", "interface_ports", "pins"):
    if k in rx:
        print("  %s:" % k)
        v = rx[k]
        if isinstance(v, dict):
            for name, info in v.items():
                dr = info.get("DIR", {})
                dv = dr.get("value") if isinstance(dr, dict) else dr
                print("    %-22s DIR=%s" % (name, dv))
print()

print("=== i2s_transmitter 暴露了哪些端口 ===")
tx = d["design"]["components"]["audio"]["components"].get("i2s_transmitter", {})
for k in ("ports", "interface_ports", "pins"):
    if k in tx:
        print("  %s:" % k)
        v = tx[k]
        if isinstance(v, dict):
            for name, info in v.items():
                dr = info.get("DIR", {})
                dv = dr.get("value") if isinstance(dr, dict) else dr
                print("    %-22s DIR=%s" % (name, dv))
print()

print("=== 所有含 sclk_out 的网络 ===")
for m in sorted(set(re.findall(r'"([a-z_0-9]*sclk_out[a-z_0-9]*)"', txt))):
    print("  ", m)
print()
print("=== audio 组件的所有网络（看还有没有别的可用源）===")
nets = d["design"]["components"]["audio"].get("nets", {})
for n in sorted(nets.keys()):
    ports = nets[n].get("ports", [])
    print("  %-38s %s" % (n, ports))