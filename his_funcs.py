#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""his_funcs.py —— 核实 PS 侧外设/交互器件, 为"功能清单"提供依据"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dtbdump import parse, fmt_val

HIS = r"D:\总文件夹\FPGA2026\_ref_boot\fit\fdt-7020.dtb"

WANT = re.compile(r"^/(leds|keys|beep|phy0|amba/(adc|gpio|i2c|spi|serial|can|ethernet|mmc|usb|watchdog|devcfg)|"
                  r"amba/spi@e000d000|amba/i2c@e0005000|amba/mmc@e0100000|amba/mmc@e0101000|"
                  r"amba/ethernet@e000b000|amba/ethernet@e000c000|amba/usb|amba/adc@f8007100)")


def main():
    data = open(HIS, "rb").read()
    _, _, tree = parse(data)
    nodes, order, stack = {}, [], []
    for depth, kind, payload in tree:
        if kind == "node":
            stack = stack[:depth]
            stack.append(payload)
            pth = "/" + "/".join(x for x in stack if x != "/")
            nodes.setdefault(pth, [])
            order.append(pth)
        elif kind == "prop":
            k, v = payload
            nodes["/" + "/".join(x for x in stack if x != "/")].append((k, v))

    KEY = ("compatible", "reg", "status", "interrupts", "interrupt-names",
           "label", "gpios", "gpio-keys", "linux,code", "linux,default-trigger",
           "xlnx,channels", "phy-mode", "phy-handle", "dr_mode", "bus-width",
           "non-removable", "is-dual", "clock-frequency", "pinctrl-names",
           "reset-gpios", "cd-gpios", "wp-gpios", "eeprom", "mac-address")

    seen = set()
    for pth in order:
        if not WANT.search(pth):
            continue
        if pth in seen:
            continue
        seen.add(pth)
        print("== " + pth)
        for k, v in nodes[pth]:
            if k in KEY or k.startswith("xlnx,chan") or k.startswith("linux,"):
                print("      %-24s = %s" % (k, fmt_val(v)))
        print()

    print("=" * 70)
    print("XADC 通道")
    for pth in order:
        if pth.startswith("/amba/adc@f8007100"):
            print("  " + pth)
            for k, v in nodes[pth]:
                print("      %-22s = %s" % (k, fmt_val(v)))


main()
