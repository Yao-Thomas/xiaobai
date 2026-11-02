#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_dataset.py —— 验证生成的波形数据集（格式 + 编码 + 内容）

★ 为什么要单独写成文件：Windows 控制台默认 GBK，
  在 `python -c "..."` 里 print 一个 ✓ 就会 UnicodeEncodeError。
  写成文件并在开头 reconfigure stdout 就能避开。

用法:
    python verify_dataset.py <数据集目录>
"""
import array
import collections
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

d = sys.argv[1] if len(sys.argv) > 1 else r"D:\ubuntu_iso\wave_dataset_test"
ok = True


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


print("=" * 74)
print(" 数据集验证: %s" % d)
print("=" * 74)

# ---- 文件存在 ----
print("\n【1】文件")
for name in ("images.bin", "labels.bin", "meta.json"):
    p = os.path.join(d, name)
    exist = os.path.exists(p)
    chk(exist, "%-12s %s" % (name, ("%d 字节" % os.path.getsize(p))
                             if exist else "★ 缺失"))

# ---- meta.json 编码 ----
print("\n【2】meta.json 编码（★ 重点：必须是 UTF-8）")
p = os.path.join(d, "meta.json")
raw = open(p, "rb").read()
try:
    txt = raw.decode("utf-8")
    chk(True, "是合法 UTF-8")
    meta = json.loads(txt)
except UnicodeDecodeError as e:
    chk(False, "不是 UTF-8", str(e)[:70])
    meta = None
except Exception as e:
    chk(False, "JSON 解析失败", str(e)[:70])
    meta = None

if meta:
    cn = meta.get("class_names_cn", [])
    chk(all(isinstance(x, str) and x and "?" not in x for x in cn),
        "中文类别名正常（没乱码）")
    print("       %s" % "  ".join(cn))
    print("       类别数 = %d" % len(cn))

    # ---- 尺寸一致性 ----
    print("\n【3】尺寸与标签")
    n = meta["count"]
    sz = meta["image_bytes"]
    imgs = open(os.path.join(d, "images.bin"), "rb").read()
    lbls = open(os.path.join(d, "labels.bin"), "rb").read()
    chk(len(imgs) == n * sz, "images.bin = count × image_bytes",
        "%d vs %d" % (len(imgs), n * sz))
    chk(len(lbls) == n, "labels.bin = count", "%d vs %d" % (len(lbls), n))

    cnt = collections.Counter(lbls)
    chk(len(cnt) == len(meta["classes"]),
        "标签覆盖了全部 %d 类" % len(meta["classes"]),
        "实际 %d 类" % len(cnt))
    chk(all(v == meta["per_class"] for v in cnt.values()),
        "每类数量均衡 = %d" % meta["per_class"],
        str(dict(sorted(cnt.items()))))

    # ---- 内容合理性 ----
    print("\n【4】图像内容")
    mx = []
    mn = []
    mean = []
    for i in range(n):
        img = imgs[i * sz:(i + 1) * sz]
        if not img:
            continue
        mx.append(max(img))
        mn.append(min(img))
        mean.append(sum(img) / len(img))
    chk(max(mx) <= 127, "所有图都 ≤ 127（int8 范围）", "最大 %d" % max(mx))
    chk(min(mn) >= 0, "所有图都 ≥ 0", "最小 %d" % min(mn))
    chk(max(mean) - min(mean) > 5, "不同图的均值有分布（不是全一样）",
        "均值范围 %.1f ~ %.1f" % (min(mean), max(mean)))

    # 每类的均值应该不同（说明类别之间有区分）
    class_means = {}
    for ci in range(len(meta["classes"])):
        vals = [mean[i] for i in range(n) if lbls[i] == ci]
        if vals:
            class_means[meta["classes"][ci]] = sum(vals) / len(vals)
    print("       各类平均亮度:")
    for k, v in class_means.items():
        print("         %-10s %.1f" % (k, v))
    spread = max(class_means.values()) - min(class_means.values())
    chk(spread > 10, "类别之间的平均亮度差异明显", "差 %.1f" % spread)

print()
print("=" * 74)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 74)
sys.exit(0 if ok else 1)
