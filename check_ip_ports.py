import re
t = open(r"D:\ubuntu_iso\gpu_ip\component.xml", encoding="utf-8", errors="replace").read()

ports = re.findall(r'<spirit:port>\s*<spirit:name>([^<]+)</spirit:name>.*?<spirit:direction>([^<]+)</spirit:direction>', t, re.S)
print("物理端口 (%d 个):" % len(ports))
for n, d in ports:
    print("  %-18s %s" % (n, d))

ifaces = re.findall(r'<spirit:busInterface>\s*<spirit:name>([^<]+)</spirit:name>.*?<spirit:busType spirit:name="([^"]+)"', t, re.S)
print("\n总线接口 (%d 个):" % len(ifaces))
for n, b in ifaces:
    print("  %-18s %s" % (n, b))

clks = re.findall(r'<spirit:clock>\s*<spirit:name>([^<]+)</spirit:name>', t)
print("\ninterface 上的时钟关联:", clks)

rsts = re.findall(r'<spirit:reset>\s*<spirit:name>([^<]+)</spirit:name>', t)
print("interface 上的复位关联:", rsts)

# 每个 aximm 接口的 associated busif / clock
for m in re.finditer(r'<spirit:busInterface>(.*?)</spirit:busInterface>', t, re.S):
    blk = m.group(1)
    nm = re.search(r'<spirit:name>([^<]+)</spirit:name>', blk)
    bt = re.search(r'<spirit:busType spirit:name="([^"]+)"', blk)
    ab = re.search(r'<spirit:associatedBusif>([^<]+)</spirit:associatedBusif>', blk)
    if bt and "aximm" in bt.group(1):
        print("\n接口 %s (%s)" % (nm.group(1) if nm else "?", bt.group(1)))
        print("  associatedBusif: %s" % (ab.group(1) if ab else "(无)"))
        # 该接口下的 port map
        for pm in re.finditer(r'<spirit:logicalPort>\s*<spirit:name>([^<]+)</spirit:name>\s*</spirit:logicalPort>\s*<spirit:physicalPort>\s*<spirit:name>([^<]+)</spirit:name>', blk):
            print("    %-12s -> %s" % (pm.group(1), pm.group(2)))
