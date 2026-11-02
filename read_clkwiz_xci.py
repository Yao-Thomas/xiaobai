#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""read_clkwiz_xci.py —— 直接从 Vivado 工程读 clk_wiz 的配置（设计意图的准确来源）"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = r"D:\ubuntu_iso\atk2026\Navigator_7020"
XCI = os.path.join(BASE, "Navigator_7020.srcs", "sources_1", "bd", "system",
                   "ip", "system_clk_wiz_0_0", "system_clk_wiz_0_0.xci")

WANT = re.compile(r"^(CLKOUT[1-7]_(REQUESTED_OUT_FREQ|USED|ACTIVE|DRIVES|"
                  r"REQUESTED_PHASE|REQUESTED_DUTY_CYCLE|JITTER|MATCHED_ROUTING)|"
                  r"PRIM_IN_FREQ|PRIMITIVE|MMCM_CLKOUT[0-6]_DIVIDE(_F)?|"
                  r"MMCM_CLKFBOUT_MULT(_F)?|MMCM_DIVCLK_DIVIDE|NUM_OUT_CLKS|"
                  r"CLK_OUT[1-7]_PORT|USE_LOCKED|CLKIN1_JITTER_PS|"
                  r"CLKOUT[1-7]_PORT|MMCM_CLKIN[12]_JITTER|USE_RESET|USE_POWER_SAVING)$")


def walk(obj, out, prefix=""):
    if isinstance(obj, dict):
        if "value" in obj and isinstance(obj["value"], str):
            out[prefix] = obj["value"]
        for k, v in obj.items():
            walk(v, out, k if not prefix else prefix + "." + k)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, out, prefix)


def main():
    s = open(XCI, encoding="utf8", errors="replace").read()
    out = {}
    try:
        walk(json.loads(s), out)
    except Exception:
        # xci 里有注释，退化为正则
        for m in re.finditer(r'"([A-Za-z0-9_]+)"\s*:\s*\{\s*"value"\s*:\s*"([^"]*)"', s):
            out[m.group(1)] = m.group(2)
    print("=== clk_wiz_0 配置 (%d 项) ===" % len(out))
    pat = re.compile(r"CLKOUT[1-7]_(REQUESTED_OUT_FREQ|USED|ACTIVE|DRIVES|"
                     r"REQUESTED_PHASE|REQUESTED_DUTY_CYCLE)|PRIM_IN_FREQ|"
                     r"MMCM_CLKOUT[0-6]_DIVIDE|MMCM_CLKFBOUT_MULT|MMCM_DIVCLK_DIVIDE|"
                     r"NUM_OUT_CLKS|CLK_OUT[1-7]_PORT|USE_LOCKED|PRIMITIVE|"
                     r"CLKOUT[1-7]_PORT")
    for k in sorted(out):
        if pat.search(k):
            print("  %-46s = %s" % (k, out[k]))
    print()
    print("=== 所有含 CLKOUT 的项 ===")
    for k in sorted(out):
        if "CLKOUT" in k:
            print("  %-46s = %s" % (k, out[k]))


main()
