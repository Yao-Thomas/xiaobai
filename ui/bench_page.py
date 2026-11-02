#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_page.py —— 三种文本类型的分页性能基准"""
import io
import os
import sys
import time

UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, UI)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import apps_novel as N

CASES = {
    "纯中文": ("这是一段用于测试分页性能的中文文本，主要用来模拟长篇小说里的段落内容。\n" * 40) * 3000,
    "中文夹英文(真实网文)": (
        "他说：“Hello world”，然后拿起 2024 年的第 3 本书，翻了 120 页。"
        "这段用来模拟网文里常见的混排，比如 a piece of cake 这种。\n") * 6000,
    "纯英文": ("The quick brown fox jumps over the lazy dog. " * 12 + "\n") * 3000,
    "重混排": ("这是 mixed 文本 with English words 和数字 12345 混在一起 "
             "testing pagination 性能。\n") * 6000,
}

for label, t in CASES.items():
    sample = t[:200000]
    dens = N._w(sample) / max(1, len(sample))
    t0 = time.time()
    s = N.paginate(t, 33, 10)
    dt = time.time() - t0
    print("%-22s %6.2f MB  密度%.2f  %6d 页  分页 %6.0f ms"
          % (label, len(t.encode("utf8")) / 1e6, dens, len(s), dt * 1000))
