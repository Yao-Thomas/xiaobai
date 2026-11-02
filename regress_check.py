#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regress_check.py —— 回归清单硬件部分（v2，抗 SIGBUS）

v1 的问题：一次 mmap 后连续读多个地址，遇到"未映射的地址"（比如
bitstream 里还没有的 CNN IP）会触发 SIGBUS，整个脚本挂掉。

v2：每个地址在**独立子进程**里读。子进程被信号打死也没关系，
    父进程能区分"bus error（地址不存在）"和"读到真实值"。

用途：刷 bitstream 前后各跑一次对比。
★ 全程只读。
"""
import json
import os
import struct
import subprocess
import sys

# ---------------- 子进程：读一个 32 位寄存器 ----------------
CHILD = r'''
import mmap, os, struct, sys
base = int(sys.argv[1], 16); off = int(sys.argv[2], 16)
try:
    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
    v = struct.unpack("<I", m[off:off+4])[0]
    m.close(); os.close(fd)
    print("VAL 0x%08X" % v)
except Exception as e:
    print("ERR %s: %s" % (type(e).__name__, e))
'''


def rd32(base, off):
    """返回 (状态, 值)。状态: 'val' / 'bus' / 'err'"""
    try:
        p = subprocess.run([sys.executable, "-c", CHILD, hex(base), hex(off)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=10)
        out = p.stdout.decode(errors="replace").strip()
        if out.startswith("VAL "):
            return "val", int(out.split()[1], 16)
        if p.returncode < 0 or "Bus" in out or p.returncode in (135, -7):
            return "bus", None
        return "err", out[:80]
    except subprocess.TimeoutExpired:
        return "err", "timeout"
    except Exception as e:
        return "err", str(e)[:80]


def chk_ip(name, base, off, expect=None):
    st, v = rd32(base, off)
    if st == "val":
        extra = ""
        if expect is not None:
            if v == expect:
                extra = "  ✓ 匹配"
                try:
                    extra += " ('%s')" % struct.pack("<I", v).decode("ascii")
                except Exception:
                    pass
            else:
                extra = "  ✗ 期望 0x%08X" % expect
        print("  [值] %-12s @0x%08X +0x%02X = 0x%08X%s" % (name, base, off, v, extra))
        return v
    if st == "bus":
        print("  [不存在] %-12s @0x%08X  →  BUS ERROR（该地址在 PL 里没映射）"
              % (name, base))
        return None
    print("  [错误] %-12s @0x%08X  →  %s" % (name, base, v))
    return None


print("=" * 68)
print(" 回归检查（硬件部分）  —— 刷写前基线")
print("=" * 68)

print()
print("--- 1. 自研 IP 在线检查 ---")
print("  （'[值]' = 该地址在 PL 里有东西；'[不存在]' = 没映射，SIGBUS）")
chk_ip("scope_0",  0x43CC0000, 0x34, 0x53434F50)
chk_ip("gpu_0",    0x43CB0000, 0x34, None)
chk_ip("cnn_conv", 0x43CD0000, 0x00, None)
chk_ip("cnn_fc",   0x43CE0000, 0x00, None)

print()
print("--- 2. 音频 codec (ES8388 @ i2c-1 0x10) ---")
for reg, nm in [(0x00, "芯片控制1"), (0x1D, "DAC Ctrl8"),
                (0x2E, "Output1-L"), (0x30, "Output2-L")]:
    try:
        out = subprocess.run(["i2cget", "-f", "-y", "1", "0x10", "0x%02x" % reg],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=5)
        print("  reg 0x%02X %-10s = %s" % (reg, nm, out.stdout.decode().strip()))
    except Exception as e:
        print("  reg 0x%02x 读取失败: %s" % (reg, e))

print()
print("--- 3. 服务状态 ---")
for s in ("zynq-desktop", "zynq-audio", "zynq-agent"):
    try:
        out = subprocess.run(["systemctl", "is-active", s],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=5)
        print("  %-16s %s" % (s, out.stdout.decode().strip()))
    except Exception as e:
        print("  %-16s 查询失败: %s" % (s, e))

print()
print("--- 4. agent HTTP API ---")
try:
    import urllib.request
    r = urllib.request.urlopen("http://127.0.0.1:8765/tools", timeout=5)
    d = json.loads(r.read().decode())
    print("  ✓ /tools 响应，工具数 = %s" % d.get("count", "?"))
    # ★ 2026-10-01 修：tools 是 [{"name":..,"description":..}, ...]，
    #   不是字符串列表；直接 join 会报 "expected str instance, dict found"
    _tools = d.get("tools", [])
    _names = []
    for t in _tools[:16]:
        _names.append(t.get("name", "?") if isinstance(t, dict) else str(t))
    print("    工具: %s" % ", ".join(_names))
except Exception as e:
    print("  ✗ /tools 失败: %s" % e)

print()
print("--- 5. 帧缓冲（桌面）---")
for f, nm in [("/sys/class/graphics/fb0/virtual_size", "virtual_size"),
              ("/sys/class/graphics/fb0/bits_per_pixel", "bpp"),
              ("/sys/class/graphics/fb0/stride", "stride")]:
    try:
        print("  %-14s = %s" % (nm, open(f).read().strip()))
    except Exception as e:
        print("  %-14s 读取失败: %s" % (nm, e))

print()
print("--- 6. 关键进程 ---")
# ★ 2026-10-01 修：模式以 "-" 开头时 pgrep 会当成选项（报 invalid option -- 'm'），
#   所以要加 "--" 终止选项解析。
for pat, nm in [("desktop.py", "桌面"), ("audio_alsa_svc", "音频服务"),
                ("-m agent.main", "agent")]:
    try:
        out = subprocess.run(["pgrep", "-af", "--", pat], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=5)
        txt = out.stdout.decode().strip()
        print("  %-10s %s" % (nm, (txt[:88] if txt else "（未找到）")))
    except Exception as e:
        print("  %-10s 查询失败: %s" % (nm, e))

print()
print("=" * 68)
print(" 检查完成")
print("=" * 68)
