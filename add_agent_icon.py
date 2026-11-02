#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「系统管家小白」放到桌面**第 1 页左上角第一位**（最显眼），把「小说」挪到第 2 页。

桌面图标布局存在 /home/zynq/.desktop_pages (JSON, root 所有)，
**不在 APPS 里** —— 光注册 APPS 是看不到图标的（这是个坑）。
"""
import json
import shutil

P = "/home/zynq/.desktop_pages"
NAME = "系统管家小白"
EVICT = "小说"          # 腾位置：挪到第 2 页

with open(P, encoding="utf-8") as f:
    pages = json.load(f)

print("改前:", json.dumps(pages, ensure_ascii=False))

while len(pages) < 2:
    pages.append([])
for pg in pages:
    while len(pg) < 12:
        pg.append(None)

# 幂等：先清掉旧位置
for pg in pages:
    for i, v in enumerate(pg):
        if v == NAME:
            pg[i] = None

p1 = [v for v in pages[0] if v not in (None, NAME)]
# 把被挤掉的那个挪到第 2 页
if EVICT in p1:
    p1.remove(EVICT)
p2 = [v for v in pages[1] if v not in (None, NAME, EVICT)]
p2.append(EVICT)

p1 = ([NAME] + p1)[:12]
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
