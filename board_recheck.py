#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_recheck.py —— 板子回来后: 确认比特流 + 探测示波器 + 检查上次为什么掉线"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

SCRIPT = r'''
echo "=== SD 上的 system.bit ==="
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -l /mnt/boot/system.bit* 2>/dev/null
echo -n "当前 system.bit md5: "; md5sum /mnt/boot/system.bit | cut -d' ' -f1
echo -n "备份 bak_before_gpu md5: "
[ -f /mnt/boot/system.bit.bak_before_gpu ] && md5sum /mnt/boot/system.bit.bak_before_gpu | cut -d' ' -f1 || echo "(无)"
umount /mnt/boot 2>/dev/null
echo
echo "=== 本地那份 scope 比特流的 md5 应该是 ==="
echo "d41d8cd98f00b204e9800998ecf8427e  (占位, 由上位机比对)"
echo
echo "=== u-boot 加载 PL 的日志 ==="
dmesg 2>/dev/null | grep -i -E "fpga|bitstream|devcfg" | tail -10
echo
echo "=== WiFi 相关 (看上次为什么掉线) ==="
dmesg 2>/dev/null | grep -i -E "aic|wlan|wifi|sdio" | tail -12
echo
echo "=== .guard_pause 还在吗 ==="
ls -l /home/zynq/.guard_pause 2>/dev/null || echo "(无)"
'''

PROBE = r'''
cd /home/zynq/ui
python3 - <<'PYEOF'
import ctypes, mmap, os, struct, sys
def rd(base, off):
    f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                  offset=base + off)
    v = struct.unpack("<I", m[0:4])[0]
    m.close(); os.close(f)
    return v
for name, base in (("GPU  0x43CB0000", 0x43CB0000),
                   ("SCOPE 0x43CC0000", 0x43CC0000)):
    pid = os.fork()
    if pid == 0:
        try:
            v = rd(base, 0)
            print("  %-18s 可读, CTRL=0x%08X" % (name, v))
        except Exception as e:
            print("  %-18s 异常 %s" % (name, e))
        os._exit(0)
    _, st = os.waitpid(pid, 0)
    if st != 0:
        print("  %-18s ✗ 进程被杀 (SIGBUS = 该地址没解码)" % name)
PYEOF
'''


def root_run(script, tag, timeout=180):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    board.put(local, "/tmp/_%s.sh" % tag)
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_%s.sh" % (board.PASS, tag),
                       timeout=timeout)
    print(out)


if __name__ == "__main__":
    root_run(SCRIPT, "recheck")
    print("=" * 60)
    print(" 安全探测 (每个地址 fork 一个子进程, SIGBUS 只杀子进程)")
    print("=" * 60)
    root_run(PROBE, "probe")
