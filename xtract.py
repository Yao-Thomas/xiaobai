#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从内核 tar.gz 里按关键字找成员并解出来"""
import sys, tarfile, os

TAR = r"D:\ubuntu_iso\_kernel_atk.tar.gz"
OUT = r"D:\ubuntu_iso\_ksrc"

pats = sys.argv[1:]
tf = tarfile.open(TAR, "r:gz")
hits = []
for m in tf:
    if not m.isfile():
        continue
    n = m.name
    for p in pats:
        if p in n:
            hits.append(n)
            break
if not hits:
    print("no match")
for n in hits:
    print(n)
