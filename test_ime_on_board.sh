#!/bin/bash
# 在板子上验证本地拼音输入法
cd /home/zynq/ui || exit 1
echo "=== 数据表 ==="
ls -l ime_cn.json ime_cn.py
echo
echo "=== 加载 + 查询测试 ==="
python3 - <<'PY'
import sys, time
sys.path.insert(0, "/home/zynq/ui")
t0 = time.time()
from ime_cn import IME
ime = IME()
t1 = time.time()
print("  加载耗时: %.2f 秒" % (t1 - t0))
print("  数据表信息:", ime.stats())
print()
t0 = time.time()
for p in ("xianzai", "yinyue", "bofang", "tianqi", "shijian",
          "xianz", "hao", "ni", "ji", "z"):
    cs = ime.candidates(p)
    print("  %-9s -> %s" % (p, " | ".join(x[0] for x in cs[:7])))
t1 = time.time()
print()
print("  10 次查询共 %.1f 毫秒" % ((t1 - t0) * 1000))
PY
echo
echo "=== 内存占用检查（板子只有 1GB）==="
free -m | head -2
