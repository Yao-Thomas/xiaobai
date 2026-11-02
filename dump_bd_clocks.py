#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_bd_clocks.py —— 从 block design 里挖出 aud_bclk / aud_daclrc / aud_adclrc 的连接

Codex 交接说：原设计 aud_bclk = TX sclk_out OR RX sclk_out（两个时钟相或）。
他自己改成 TX-only，结果完全无声。

原理图证实：ES8388 的 LRCK(pin7) 接的是 AUD_ADCLRC（接收器一侧）。
=> 若 BCLK 来自 TX、LRCK 来自 RX，两者不同源，codec 无法工作。
   正确做法可能是让 BCLK 也来自 RX。

这个脚本把 BD 里的实际连接挖出来看。
"""
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BD = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.srcs"
      r"\sources_1\bd\system\system.bd")

raw = open(BD, encoding="utf-8", errors="replace").read()
print("=" * 84)
print("block design 的音频时钟连接")
print("=" * 84)
print("  BD: %s" % BD)
print()

# BD 是 JSON，但可能带一点非标准；先试着直接解析
try:
    d = json.loads(raw)
    print("  JSON 解析成功")
except Exception as e:
    print("  JSON 解析失败(%s)，改用文本搜索" % str(e)[:50])
    d = None
print()

# ---- 1) 找 aud_ 端口所在的端口定义 ----
print("--- 1) aud_* 端口定义（方向 / 位宽）---")
for m in re.finditer(r'\{\s*"[^"]*"\s*:\s*\{[^{}]*"aud_[a-z_]+"[^{}]*\}', raw):
    pass
# 直接按名字找
for name in ("aud_bclk", "aud_daclrc", "aud_adclrc", "aud_dacdat",
             "aud_adcdat", "aud_mclk"):
    idx = raw.find('"%s"' % name)
    hits = []
    while idx != -1:
        seg = raw[max(0, idx - 260):idx + 260]
        if "DIR" in seg or "LEFT" in seg or "PORT" in seg or "interface" in seg.lower():
            hits.append(seg)
        idx = raw.find('"%s"' % name, idx + 1)
    print("  %s: 找到 %d 处带方向信息的上下文" % (name, len(hits)))
    if hits:
        s = hits[0].replace("\n", " ").replace("\r", "")
        # 提取 DIR
        dm = re.search(r'"DIR"\s*:\s*\{[^}]*"value"\s*:\s*"([^"]+)"', s)
        print("      DIR=%s" % (dm.group(1) if dm else "?"))
print()

# ---- 2) 找 nets：谁驱动 aud_bclk ----
print("--- 2) 找驱动 aud_bclk / aud_daclrc / aud_adclrc 的网络 ---")
for name in ("aud_bclk", "aud_daclrc", "aud_adclrc"):
    print("  [%s]" % name)
    # 所有出现的 "port" 引用
    pat = re.compile(r'"[^"]*%s"' % re.escape(name))
    ports = set(m.group(0).strip('"') for m in pat.finditer(raw))
    for p in sorted(ports):
        print("    port: %s" % p)
    # 该名字附近的 pin 引用
    for m in re.finditer(re.escape(name), raw):
        seg = raw[max(0, m.start() - 400):m.start() + 200]
        pins = re.findall(r'"system_[a-z_0-9]+/[A-Za-z_0-9]+"', seg)
        if pins:
            print("    附近 pin: %s" % sorted(set(pins))[:6])
            break
print()

# ---- 3) 找 util_vector_logic（OR 门）的输入输出 ----
print("--- 3) util_vector_logic 实例（找 OR 门）---")
for m in re.finditer(r'system_util_vector_logic[_0-9]*', raw):
    pass
names = sorted(set(re.findall(r'"system_util_vector_logic[_0-9]*"', raw)))
print("  实例: %s" % names)
for n in names[:6]:
    nn = n.strip('"')
    idx = raw.find('"%s"' % nn)
    seg = raw[idx:idx + 3000]
    op = re.search(r'"OP"\s*:\s*\{[^}]*"value"\s*:\s*"([^"]+)"', seg)
    pins = re.findall(r'"%s/([A-Za-z_0-9]+)"' % re.escape(nn), seg)
    print("    %-34s OP=%-6s pins=%s"
          % (nn, op.group(1) if op else "?", sorted(set(pins))[:8]))
print()

print("★ 要看的：aud_bclk 是被 util_vector_logic（OR 门）驱动，")
print("  还是被 system_i2s_transmitter_0/sclk_out 或 receiver_0/sclk_out 直接驱动。")
