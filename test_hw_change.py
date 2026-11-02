#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_hw_change.py —— 离线验证变更/回滚机制（三条路径都要走到）

要验证的核心行为：
  A 变更成功          -> 文件改了、变更单记"已应用"、不回滚
  B 命令失败          -> 自动回滚、文件回到原样、变更单记"已回滚"
  C 验证不通过        -> 自动回滚（把 verify_all 打桩成"必失败"）
  D 手工回滚          -> 能把某次变更涉及的文件夹恢复原样

★ 特别要测 C：这才是"改错了不会把板子留在坏状态"的关键。

用法:
    python test_hw_change.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import agent.hw_change as HC                                    # noqa: E402

ok = True


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


# 用临时目录，别污染系统
TMP = tempfile.mkdtemp(prefix="hwchange_test_")
HC.CHANGE_DIR = os.path.join(TMP, "changes")
HC.CHANGE_FILE = os.path.join(HC.CHANGE_DIR, "changes.jsonl")
HC.SNAPSHOT_DIR = os.path.join(HC.CHANGE_DIR, "snapshots")

F1 = os.path.join(TMP, "a.txt")
F2 = os.path.join(TMP, "b.txt")
PY = sys.executable          # 用当前解释器，跨平台都能跑


def write(p, s):
    with open(p, "w") as f:
        f.write(s)


def rd(p):
    with open(p) as f:
        return f.read()


def setfile(p, s):
    """生成一条"把文件内容改成 s"的命令（跨平台安全）"""
    return '"%s" -c "open(r\'%s\',\'w\').write(r\'%s\')"' % (PY, p, s)


def reset():
    write(F1, "原始1")
    write(F2, "原始2")


print("=" * 74)
print(" 变更/回滚机制离线验证")
print("=" * 74)
print(" 临时目录: %s" % TMP)

# ══════════════════════════════════════════════════════════════ A
print("\n【A】变更成功 -> 保留，不回滚")
reset()
okA, msgA = HC.apply_change(
    "test", "把 a.txt 改成 新内容A",
    actions=[("改 a.txt", setfile(F1, "新内容A"))],
    paths=[F1, F2], skip_verify=True, verbose=False)
chk(okA, "apply_change 返回成功", msgA[:70])
chk(rd(F1) == "新内容A", "a.txt 已改成 '新内容A'", repr(rd(F1)))
chk(rd(F2) == "原始2", "b.txt 未受影响", repr(rd(F2)))

# ══════════════════════════════════════════════════════════════ B
print("\n【B】命令失败 -> 自动回滚")
reset()
okB, msgB = HC.apply_change(
    "test", "先改 b.txt 再执行一条必失败的命令",
    actions=[("改 b.txt", setfile(F2, "脏数据")),
             ("必失败", '"%s" -c "import sys; sys.exit(3)"' % PY)],
    paths=[F1, F2], skip_verify=True, verbose=False)
chk(not okB, "apply_change 返回失败", msgB[:70])
chk(rd(F1) == "原始1", "a.txt 已回滚", repr(rd(F1)))
chk(rd(F2) == "原始2", "b.txt 已回滚（脏数据被撤销）", repr(rd(F2)))

# ══════════════════════════════════════════════════════════════ C
print("\n【C】★ 验证不通过 -> 自动回滚（最关键的一条）")
reset()
# 把验证函数打桩成"硬检查必失败"
_orig_verify = HC.verify_all


def fake_verify(verbose=True):
    checks = [{"name": "桌面 在跑", "ok": False, "hard": True,
               "detail": "打桩：假装桌面没起来"}]
    if verbose:
        print("   （打桩的验证：桌面 在跑 -> ✗）")
    return False, checks


HC.verify_all = fake_verify
okC, msgC = HC.apply_change(
    "test", "改完但验证会失败",
    actions=[("改 a.txt", setfile(F1, "不该留下的内容"))],
    paths=[F1, F2], skip_verify=False, verbose=False)
HC.verify_all = _orig_verify
chk(not okC, "apply_change 判定失败", msgC[:90])
chk(rd(F1) == "原始1", "★ a.txt 被自动回滚了", repr(rd(F1)))
chk("回滚" in msgC, "返回信息里说明了已回滚")

# ══════════════════════════════════════════════════════════════ D
print("\n【D】手工回滚指定的变更")
reset()
okD1, _ = HC.apply_change(
    "test", "改两个文件",
    actions=[("改 a", setfile(F1, "X")), ("改 b", setfile(F2, "Y"))],
    paths=[F1, F2], skip_verify=True, verbose=False)
cid = HC.change_list(1)[0]["id"]
print("   变更 id = %s" % cid)
chk(rd(F1) == "X" and rd(F2) == "Y", "两个文件都改了")
okD2, why = HC.rollback(cid, verbose=False)
chk(okD2, "rollback 返回成功", why)
chk(rd(F1) == "原始1" and rd(F2) == "原始2", "两个文件都恢复了")

# ══════════════════════════════════════════════════════════════ E
print("\n【E】变更单内容检查")
recs = HC.change_list(20)
print("   共 %d 条记录" % len(recs))
kinds = set(r.get("kind") for r in recs)
results = [r.get("result", "") for r in recs]
chk(len(recs) >= 4, "记录了至少 4 条")
chk(any("回滚" in r for r in results), "有'已回滚'的记录")
chk(any("验证通过" in r or "跳过验证" in r for r in results), "有成功记录")
# 每条都要有 id/ts/detail
good = all(r.get("id") and r.get("ts") and r.get("detail") for r in recs)
chk(good, "每条记录都有 id/时间/详情")

shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 74)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 74)
sys.exit(0 if ok else 1)
