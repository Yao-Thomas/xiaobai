#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_both.py —— 安全探测两个自研 IP (fork 子进程, SIGBUS 只杀子进程)"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

PROBE = r'''
cd /home/zynq/ui
cat > /tmp/_pb.py <<'PYEOF'
import mmap, os, struct, sys

def rd(base, off):
    f = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    m = mmap.mmap(f, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                  offset=base + off)
    v = struct.unpack("<I", m[0:4])[0]
    m.close(); os.close(f)
    return v

targets = [("GPU   0x43CB0000", 0x43CB0000, 0x00),
           ("SCOPE 0x43CC0000", 0x43CC0000, 0x34)]
for name, base, off in targets:
    pid = os.fork()
    if pid == 0:
        try:
            v = rd(base, off)
            print("  %-20s 可读   [0x%02X]=0x%08X" % (name, off, v))
            sys.stdout.flush()
        except Exception as e:
            print("  %-20s 异常 %s" % (name, e))
        os._exit(0)
    _, st = os.waitpid(pid, 0)
    if st != 0:
        print("  %-20s ✗ 被信号杀死 (SIGBUS = 该地址没解码)" % name)
PYEOF
python3 /tmp/_pb.py
'''


def main():
    local = os.path.join(HERE, "_tmp_pb.sh")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + PROBE)
    board.put(local, "/tmp/_pb.sh")
    out, _ = board.run("echo %s | sudo -S -p '' bash /tmp/_pb.sh" % board.PASS,
                       timeout=120)
    print(out)


if __name__ == "__main__":
    main()
