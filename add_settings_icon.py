#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「设置」放到桌面图标页第 1 页第 2 格，并把「提示音」放第 2 页。

桌面图标布局在 /home/zynq/.desktop_pages (JSON, root 所有)，不在 APPS 里。
被挤下来的「系统信息」挪到第 2 页（设置里也能进）。
"""
import json
import shutil

P = "/home/zynq/.desktop_pages"
WANT_P1 = ["系统管家小白", "设置"]          # 第 1 页前两格
SECOND = "提示音"                           # 放到第 2 页
EVICT = "系统信息"                          # 腾位置

with open(P, encoding="utf-8") as f:
    pages = json.load(f)
print("改前:", json.dumps(pages, ensure_ascii=False))

while len(pages) < 2:
    pages.append([])
for pg in pages:
    while len(pg) < 12:
        pg.append(None)

allv = []
for pg in pages:
    for v in pg:
        if v and v not in allv:
            allv.append(v)

# 第 1 页：固定的两格 + 其余按原顺序补齐（排除要挪走的）
rest = [v for v in allv if v not in WANT_P1 + [SECOND]]
if EVICT in rest:
    rest.remove(EVICT)
p1 = (WANT_P1 + rest)[:12]

# 第 2 页：剩下的 + 被挪走的 + 提示音
used = set(p1)
p2 = [v for v in allv if v not in used and v != SECOND]
p2 = [v for v in p2 if v != EVICT]
p2 = [SECOND] + p2 + [EVICT]
p2 = p2[:12]
while len(p2) < 12:
    p2.append(None)

pages = [p1, p2]
shutil.copy(P, P + ".bak")
with open("/tmp/_pages.json", "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False)
print("改后:", json.dumps(pages, ensure_ascii=False))
