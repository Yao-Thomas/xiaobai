#!/bin/bash
# 频谱矩阵自证（走常驻服务，不受内存碎片化影响，随时可复现）
#
# ★ 2026-09-28 更新：加了"有效性"显示。
#   服务现在会给每行标 valid（全零 = 采集整段失败 = 故障 B），
#   并在 min_flatness 上**只统计有效行**。
#
# ★ 会出声！用户同意前别跑（音频服务被封锁时它也起不来）。
echo "=== POST /matrix ==="
curl -s --max-time 300 -X POST -H 'Content-Type: application/json' \
  -d '{"secs":0.5,"amp":0.9}' http://127.0.0.1:8767/matrix > /tmp/mx.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/mx.json"))
if not d.get("ok"):
    print("失败:", d)
    raise SystemExit(1)
f = d["freqs"]
print("候选频率:", " ".join("%8.1f" % x for x in f))
print("静音基线:", " ".join("%8.1f" % x for x in d["baseline"]))
print()
print("%-9s | %-9s | %s | 判定" % ("播放Hz", "有效", " ".join("%8.1f" % x for x in f)))
print("-" * 92)
for r in d["rows"]:
    v = r.get("valid", True)
    if not v:
        jd = "Ø 全零(故障B)"
    elif r["hit"]:
        jd = "★对角线"
    else:
        jd = " 偏离→%.1f" % (r["top"] if r["top"] is not None else 0)
    print("%-9.1f | %-9s | %s | %s  峰%.0f 基线%.0f (%+.1f dB)"
          % (r["play"], "有效" if v else "无效",
             " ".join("%8.1f" % x for x in r["energy"]),
             jd, r["peak"], r["base"], r["gain_db"]))
print("-" * 92)
print("对角线命中 %d/%d   最小平坦度=%.1f   ok=%s"
      % (d["hit"], d["total"], d.get("min_flatness", 0), d.get("pass", d.get("good"))))
zv = d.get("zero_captures")
vr = d.get("valid_rows")
if zv is not None:
    print("有效性: 有效 %s/%d 行   全零(故障B) %s 行" % (vr, d["total"], zv))
    if zv:
        print("  ★ 有采集整段失败 —— 这些行**不计入**命中率和平坦度")
    else:
        print("  ★ 本次没遇到采集整段失败（故障B 未出现）")
print("结论:", d["verdict"])

# 把故障B的发生率单独摘出来，方便累计观察
if zv:
    print()
    print("【故障B 发生率】%d/%d = %.0f%%  <- 这个数本身是诊断数据"
          % (zv, d["total"], 100.0 * zv / d["total"]))
PY
