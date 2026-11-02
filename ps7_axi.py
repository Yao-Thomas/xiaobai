#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ps7_axi.py —— 提取 PS7 的 AXI 端口配置 (GPU 能不能接上的决定因素)"""
import json, re

BD = r"D:\ubuntu_iso\atk_vivado_prj\vivado_prj\Navigator_7020\Navigator_7020.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
ps = j["design"]["components"]["processing_system7_0"]
P = {k: (v.get("value") if isinstance(v, dict) else v)
     for k, v in ps.get("parameters", {}).items()}

def show(pat, title):
    print("\n---- %s ----" % title)
    hit = False
    for k in sorted(P):
        if re.search(pat, k):
            print("   %-52s = %s" % (k, P[k]))
            hit = True
    if not hit:
        print("   (无)")

show(r"USE_M_AXI|USE_S_AXI|M_AXI_GP0|S_AXI_HP|S_AXI_ACP|S_AXI_GP",
     "AXI 端口使能")
show(r"DATA_WIDTH|_WIDTH$|ID_WIDTH|ADDR_WIDTH",
     "AXI 位宽")
show(r"FREQ_HZ|FCLK|CLK.*FREQ", "时钟频率")
show(r"^PCW_DDR|^PCW_.*DDR", "DDR 配置")
show(r"USE_.*_RESET|RESET.*ENABLE", "复位")

print("\n---- PS7 接口端口 (interface_ports) ----")
for k, v in ps.get("interface_ports", {}).items():
    if isinstance(v, dict):
        print("   %-40s %s" % (k, v.get("vlnv", "") or str(list(v.keys()))[:60]))
    else:
        print("   %-40s %s" % (k, str(v)[:60]))

print("\n---- PS7 普通端口 (ports) ----")
for k, v in ps.get("ports", {}).items():
    if isinstance(v, dict):
        print("   %-40s %s" % (k, v.get("direction", "")))
    else:
        print("   %-40s %s" % (k, str(v)[:60]))
