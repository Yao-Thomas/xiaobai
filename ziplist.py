#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ziplist.py —— 列 zip 内容, 不乱解压"""
import sys
import io
import zipfile
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def show(path, limit=200):
    print("=" * 78)
    print(path)
    print("=" * 78)
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        print("  打不开: %s" % e)
        return
    infos = z.infolist()
    total = sum(i.file_size for i in infos)
    print("  条目 %d 个, 解压后 %.1f MB" % (len(infos), total / 1e6))
    print()
    # 顶层结构汇总
    tops = {}
    for i in infos:
        nm = i.filename.replace("\\", "/")
        top = nm.split("/")[0] if "/" in nm else "(根目录)"
        d = tops.setdefault(top, [0, 0])
        d[0] += 1
        d[1] += i.file_size
    print("  --- 顶层 ---")
    for t, (n, sz) in sorted(tops.items(), key=lambda kv: -kv[1][1])[:40]:
        print("    %-46s %5d 项  %9.2f KB" % (t, n, sz / 1024.0))
    print()
    print("  --- 前 %d 个文件 ---" % limit)
    shown = 0
    for i in infos:
        nm = i.filename.replace("\\", "/")
        if nm.endswith("/"):
            continue
        if shown >= limit:
            print("    ... 还有 %d 个" % (len(infos) - shown))
            break
        print("    %10d  %s" % (i.file_size, nm))
        shown += 1
    print()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        show(p)
