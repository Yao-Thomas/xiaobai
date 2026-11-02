#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_hw_tools.py —— 在没有板子的情况下验证 hw_tools.py 能正确加载

不需要真的连板子。测这些：
  ① 能不能 import（语法、依赖、循环导入）
  ② 9 个硬件工具是不是都注册进 REGISTRY 了
  ③ 每个工具的 JSON schema 合不合法（DeepSeek 的 function calling 要求严格）
  ④ 参数校验分支：给错参数会不会崩（要返回字符串，不能抛异常）
  ⑤ 只读工具在"没有板子"的环境下会不会优雅失败（而不是抛异常）

用法（在 D:\\ubuntu_iso 下）：
    python test_hw_tools.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ok = True


def chk(cond, msg, detail=""):
    global ok
    mark = "✓" if cond else "✗"
    print("   %s %s%s" % (mark, msg, ("   " + detail) if detail else ""))
    if not cond:
        ok = False


print("=" * 76)
print(" hw_tools.py 离线验证")
print("=" * 76)

# ---------------- ① 导入 ----------------
print("\n【①】导入")
try:
    from agent import tools as T
    print("   ✓ agent.tools 导入成功")
except Exception as e:
    print("   ✗ agent.tools 导入失败: %s: %s" % (type(e).__name__, e))
    sys.exit(1)

before = set(T.REGISTRY)

try:
    from agent import hw_tools as H
    print("   ✓ agent.hw_tools 导入成功")
except Exception as e:
    import traceback
    print("   ✗ agent.hw_tools 导入失败: %s: %s" % (type(e).__name__, e))
    traceback.print_exc()
    sys.exit(1)

# ★★★ 关键：把变更单的落盘位置指到临时目录
#
# 踩过：这个测试会调 hw_change_add 工具（测参数校验分支），
# 而那些调用会**真的写** /var/lib/hwchange/changes.jsonl。
# 结果板子上的变更历史里混进了 kind='' / kind='None' / detail='测试'
# 这种垃圾记录，云协同的变更列表就显示成 None 了。
# ⇒ 测试必须隔离，不能污染真实数据。
import shutil as _shutil
import tempfile as _tempfile
_TMPCH = _tempfile.mkdtemp(prefix="hwtools_ch_")
try:
    from agent import hw_change as _HC
    _HC.CHANGE_DIR = _TMPCH
    _HC.CHANGE_FILE = os.path.join(_TMPCH, "changes.jsonl")
    _HC.SNAPSHOT_DIR = os.path.join(_TMPCH, "snapshots")
    H.CHANGE_DIR = _TMPCH
    H.CHANGE_FILE = _HC.CHANGE_FILE
    print("   ✓ 变更单已隔离到临时目录（不污染板子上的真实记录）")
except Exception as e:
    print("   ⚠ 变更单隔离失败（%s）—— 测试可能写真实文件" % e)

after = set(T.REGISTRY)
added = sorted(after - before)

# ---------------- ② 注册 ----------------
print("\n【②】注册情况")
print("   原有工具 (%d): %s" % (len(before), ", ".join(sorted(before))))
print("   新增工具 (%d): %s" % (len(added), ", ".join(added)))

want = ["hw_reg_read", "hw_thermal", "hw_thermal_set", "hw_scope_capture",
        "hw_acoustic_test", "hw_change_list", "hw_change_add",
        "hw_flash_bitstream", "hw_fpga_build",
        "hw_verify", "hw_change_apply", "hw_change_rollback",
        "hw_waveform_classify", "hw_waveform_dataset",
        "hw_hdl_edit", "hw_fpga_build_status"]
for w in want:
    chk(w in added, "注册了 %s" % w)

# ---------------- ③ schema ----------------
print("\n【③】JSON schema 合法性")
for name in added:
    t = T.REGISTRY[name]
    p = t["params"]
    good = (isinstance(p, dict) and p.get("type") == "object"
            and isinstance(p.get("properties"), dict))
    if good and "required" in p:
        good = all(r in p["properties"] for r in p["required"])
    chk(good, "%-20s schema 合法" % name,
        "" if good else repr(p)[:80])
    # 能不能序列化（DeepSeek 要 POST 出去）
    try:
        json.dumps(t["params"])
    except Exception as e:
        chk(False, "%-20s schema 不能序列化: %s" % (name, e))

# 用 schemas() 生成一遍（这是真正发给 LLM 的东西）
print("\n   用 tools.schemas() 生成（真正发给模型的格式）：")
try:
    sc = T.schemas(enabled=set(added))
    chk(len(sc) == len(added), "生成了 %d 个 schema" % len(sc))
    for s in sc[:2]:
        print("      %s" % json.dumps(s, ensure_ascii=False)[:130])
except Exception as e:
    chk(False, "schemas() 失败: %s" % e)

# ---------------- ④ 参数校验 ----------------
print("\n【④】参数校验（给错参数不能崩，要返回字符串）")
cases = [
    ("hw_reg_read", {}),
    ("hw_reg_read", {"base": "不存在的IP"}),
    ("hw_reg_read", {"base": "0x99999999"}),
    ("hw_reg_read", {"base": "scope_0", "offset": "乱七八糟"}),
    ("hw_thermal", {}),
    ("hw_change_list", {"limit": "abc"}),
    ("hw_flash_bitstream", {}),
    ("hw_flash_bitstream", {"file": "/tmp/不存在.bit"}),
    ("hw_change_add", {"kind": "bd", "detail": "测试"}),
    ("hw_acoustic_test", {}),
    # ★ 下面这些专门测"模型传了烂参数"的情况 —— 工具绝不能抛异常
    ("hw_reg_read", {"base": "scope_0", "count": "abc"}),
    ("hw_reg_read", {"base": "scope_0", "count": None}),
    ("hw_reg_read", {"base": "scope_0", "count": {"x": 1}}),
    ("hw_reg_read", {"base": "scope_0", "width": "宽"}),
    ("hw_reg_read", {"base": None}),
    ("hw_reg_read", {"base": 12345}),                 # 数字也要能当地址用
    ("hw_change_list", {"limit": None}),
    ("hw_change_list", {"limit": []}),
    ("hw_change_list", {"limit": "999999"}),          # 超大值要被夹住
    ("hw_change_list", {"limit": "-5"}),              # 负数要被夹住
    ("hw_scope_capture", {"points": "很多"}),
    ("hw_thermal_set", {}),
    ("hw_thermal_set", {"warn": "热"}),
    ("hw_fpga_build", {}),
    ("hw_change_add", {}),
    ("hw_change_add", {"kind": None, "detail": None}),
]
for name, args in cases:
    try:
        r = T.call(name, args, {})
        good = isinstance(r, str)
        chk(good, "%-20s %-42s -> %s" %
            (name, json.dumps(args, ensure_ascii=False)[:42],
             (r[:70].replace("\n", " ") + "…") if len(r) > 70 else r.replace("\n", " ")))
    except Exception as e:
        chk(False, "%-20s 抛异常了！%s: %s" % (name, type(e).__name__, e))

# ---------------- ⑤ 无板子时的行为 ----------------
print("\n【⑤】没有板子时的行为（应优雅失败）")
r = T.call("hw_reg_read", {"base": "scope_0", "offset": "0x34"}, {})
print("   hw_reg_read -> %s" % r.replace("\n", " | ")[:160])
chk("读到" in r or "读不到" in r or "不能" in r,
    "hw_reg_read 返回了可读的说明（不是崩溃）")

r = T.call("hw_thermal", {}, {})
print("   hw_thermal  -> %s" % r.replace("\n", " | ")[:160])

r = T.call("hw_change_list", {}, {})
print("   hw_change_list -> %s" % r.replace("\n", " | ")[:120])

# ---------------- ⑥ 静音锁 ----------------
print("\n【⑥】静音锁")
print("   SILENT_FLAG = %s" % T.SILENT_FLAG)
print("   当前锁状态: %s" % ("★ 已锁" if T.silent_locked() else "未锁（PC 上没有这个文件，正常）"))
r = T.call("hw_acoustic_test", {}, {})
if T.silent_locked():
    chk("静音锁" in r, "锁着时会拒绝出声")
else:
    chk(isinstance(r, str), "未锁时返回字符串（%s）" % r.replace("\n", " ")[:70])

print()
print("=" * 76)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 76)
sys.exit(0 if ok else 1)
