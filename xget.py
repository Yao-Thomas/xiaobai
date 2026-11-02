#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解出指定成员到 _ksrc (平铺), 并可选 grep"""
import sys, tarfile, os, re

TAR = r"D:\ubuntu_iso\_kernel_atk.tar.gz"
OUT = r"D:\ubuntu_iso\_ksrc"

want = sys.argv[1:]
tf = tarfile.open(TAR, "r:gz")
got = {}
for m in tf:
    if not m.isfile():
        continue
    for w in want:
        if m.name.endswith(w) or m.name == w or ("/" + w) in m.name:
            data = tf.extractfile(m).read()
            base = os.path.basename(m.name)
            dst = os.path.join(OUT, base)
            with open(dst, "wb") as f:
                f.write(data)
            got[m.name] = dst
            print("extracted %s -> %s (%d bytes)" % (m.name, dst, len(data)))
            break
tf.close()
if not got:
    print("none")
