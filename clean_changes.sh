#!/bin/sh
# clean_changes.sh —— 清掉变更日志里被测试污染的记录
#
# 背景：test_hw_tools.py 会调 hw_change_add 工具测参数校验，
#       早期版本没做隔离，于是板子的真实变更日志里混进了
#       kind=''/'None'、detail='测试' 这种垃圾。
#       现在测试已经隔离了，但**历史垃圾要清掉**。

echo "======================================================"
echo " 清理变更日志"
echo "======================================================"
echo

F=/var/lib/hwchange/changes.jsonl
if [ ! -f "$F" ]; then
  echo "  $F 不存在，没什么可清"
  exit 0
fi

TS=$(date +%Y%m%d_%H%M%S)
sudo cp "$F" "$F.bak_$TS"
echo "  已备份 -> $F.bak_$TS"
echo -n "  清理前: "
sudo wc -l < "$F"
echo

sudo python3 - <<'PY'
import json, os

F = "/var/lib/hwchange/changes.jsonl"
keep, drop = [], []
for i, ln in enumerate(open(F, encoding="utf-8", errors="replace"), 1):
    ln = ln.strip()
    if not ln:
        continue
    try:
        d = json.loads(ln)
    except Exception:
        drop.append((i, "坏 JSON", ln[:60]))
        continue

    kind = d.get("kind")
    detail = d.get("detail")
    # ★ 判定垃圾记录
    bad = False
    why = ""
    if kind is None or kind == "" or str(kind) == "None":
        bad, why = True, "kind 为空/None"
    elif detail is None or detail == "" or str(detail) == "None":
        bad, why = True, "detail 为空/None"
    elif str(detail) in ("测试", "test") and not d.get("path"):
        bad, why = True, "测试数据"
    elif not d.get("id"):
        bad, why = True, "没有 id（旧格式）"

    if bad:
        drop.append((i, why, ln[:70]))
    else:
        keep.append(d)

with open(F, "w", encoding="utf-8") as f:
    for d in keep:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print("  保留 %d 条，清掉 %d 条" % (len(keep), len(drop)))
print()
if drop:
    print("  清掉的：")
    for i, why, txt in drop:
        print("    第 %d 行 [%s]" % (i, why))
print()
if keep:
    print("  保留的：")
    for d in keep:
        print("    [%s] %-10s %s" % (d.get("ts"), d.get("kind"),
                                     (d.get("detail") or "")[:50]))
PY
echo
echo -n "  清理后: "
sudo wc -l < "$F"
echo
sudo systemctl restart cloud-api
sleep 5
echo "  cloud-api: $(systemctl is-active cloud-api)"
echo
echo "=== 变更历史（应该干净了）==="
TOKEN=$(python3 -c "import json;print(json.load(open('/etc/xiaobai-cloud.json'))['token'])")
curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:8768/hw/changes?limit=10" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('  共 %d 条' % d.get('count', 0))
for c in d.get('changes', []):
    print('    [%s] %-10s id=%-22s %s' % (c.get('ts'), c.get('kind'),
          c.get('id'), (c.get('detail') or '')[:40]))
    print('        可回滚=%s  旧格式=%s' % (c.get('rollbackable'), c.get('legacy')))
"
