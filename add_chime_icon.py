#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「提示音」放到桌面图标页第 1 页第 2 格（紧挨系统管家小白，好找）。

「关于」挪到第 2 页腾位置。
桌面图标布局存在 /home/zynq/.desktop_pages (JSON, root 所有)，不在 APPS 里。
"""
import json
import shutil

P = "/home/zynq/.desktop_pages"
NEW = "提示音"
EVICT = "关于"

with open(P, encoding="utf-8") as f:
    pages = json.load(f)

print("改前:", json.dumps(pages, ensure_ascii=False))

while len(pages) < 2:
    pages.append([])
for pg in pages:
    while len(pg) < 12:
        pg.append(None)

# 幂等：先清旧位置
for pg in pages:
    for i, v in enumerate(pg):
        if v == NEW:
            pg[i] = None

p1 = [v for v in pages[0] if v not in (None, NEW)]
if EVICT in p1:
    p1.remove(EVICT)
p2 = [v for v in pages[1] if v not in (None, NEW, EVICT)]
p2.append(EVICT)

# 系统管家小白在第 1 格，提示音插到第 2 格
if p1 and p1[0] == "系统管家小白":
    p1 = [p1[0], NEW] + p1[1:]
else:
    p1 = [NEW] + p1
p1 = p1[:12]
while len(p1) < 12:
    p1.append(None)
p2 = p2[:11]
while len(p2) < 12:
    p2.append(None)

pages[0] = p1
pages[1] = p2
pages = pages[:2]

shutil.copy(P, P + ".bak")
with open("/tmp/_pages.json", "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False)
print("改后:", json.dumps(pages, ensure_ascii=False))
