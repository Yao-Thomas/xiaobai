#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_tools_policy.py —— 把 policy.py 的三态判定接进工具

改三个工具：
  shell  —— allow 直跑 / deny 拒绝 / confirm 走"待批准"
  write  —— 受保护目录要批准
  edit   —— 同上

confirm 的流程：
    第一次调用 -> policy.request() 登记，返回"需要用户批准 (id=..)"
    用户在 UI 上点同意 -> resolve(id, True) -> 动作进入 5 分钟白名单
    模型重试同一条命令 -> is_approved() 命中 -> 直接执行
"""
import io
import re
import sys

P = "agent/tools.py"
src = io.open(P, encoding="utf-8").read()

if "policy" in src and "_policy_gate" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ───────────────────────────── 1) import + 闸门函数
if "from . import policy" not in src:
    src = src.replace("from . import spill",
                      "from . import spill\nfrom . import policy", 1)
    print("  OK: import policy")

GATE = '''

# ══════════════════════════════════════════════════════════════════
#  权限闸门（2026-09-28 事故后加）
#
#  事故回顾：用户说"不要再播放了"，Agent 自己用 shell 把音频服务拉起来
#  放音 —— 两次。根因是 Agent 有不受限的 root shell 且没有"该不该做"概念。
#
#  现在所有 shell/write/edit 都先过 policy.classify_*：
#      allow   直跑
#      deny    拒绝并说明原因
#      confirm 登记待批准，返回给模型让它问用户
# ══════════════════════════════════════════════════════════════════
def _policy_gate(kind, payload):
    """返回 None 表示放行；返回字符串表示要中止并把这句话回给模型"""
    try:
        if kind == "shell":
            dec, why = policy.classify_shell(payload)
        else:
            dec, why = policy.classify_write(payload)
    except Exception as e:
        return "【权限层异常】%s —— 为安全起见拒绝执行" % e

    if dec == "allow":
        return None
    if policy.is_approved(kind, payload):
        return None

    if dec == "deny":
        return "【权限层拒绝】%s\\n（要改这条规则：编辑 %s）" % (
            why, policy.POLICY_FILE)

    rid = policy.request(kind, payload, why)
    return ("【需要用户批准】%s\\n"
            "已登记为待批准动作 id=%s。请告诉用户你想做什么、为什么，"
            "请他在界面上点「同意」或「拒绝」。**不要自己绕过。**"
            % (why, rid))

'''
src = src.replace("def schemas(enabled=None):", GATE + "\ndef schemas(enabled=None):", 1)
print("  OK: 加了 _policy_gate()")

# ───────────────────────────── 2) shell 工具插入闸门
m = re.search(r'@tool\(\s*"shell"(.*?)\ndef\s+(\w+)\(', src, re.S)
if m:
    fn = m.group(2)
    # 闸门插在函数体开头；shell 的参数名是 cmd
    pat = re.compile(r"(def\s+%s\(([^)]*)\):\s*\n)" % re.escape(fn))
    mm = pat.search(src)
    if mm:
        args = mm.group(2)
        argname = "cmd" if "cmd" in args else args.split(",")[0].strip().split("=")[0].strip()
        ins = (mm.group(1) +
               "    _g = _policy_gate(\"shell\", %s)\n"
               "    if _g:\n"
               "        return _g\n" % argname)
        src = src[:mm.start(1)] + ins + src[mm.end(1):]
        print("  OK: shell 工具已接闸门（参数 %s）" % argname)
    else:
        print("  [!] shell 函数体没匹配到")
else:
    print("  [!] 没找到 shell 工具")

# ───────────────────────────── 3) write / edit 插入闸门
for tname, arg in (("write", "path"), ("edit", "path")):
    m2 = re.search(r'@tool\(\s*"%s"(.*?)\ndef\s+(\w+)\(' % tname, src, re.S)
    if not m2:
        print("  [!] 没找到 %s 工具" % tname)
        continue
    fn2 = m2.group(2)
    pat2 = re.compile(r"(def\s+%s\(([^)]*)\):\s*\n)" % re.escape(fn2))
    mm2 = pat2.search(src)
    if not mm2:
        print("  [!] %s 函数体没匹配到" % tname)
        continue
    args2 = mm2.group(2)
    an = arg if arg in args2 else args2.split(",")[0].strip().split("=")[0].strip()
    ins2 = (mm2.group(1) +
            "    _g = _policy_gate(\"write\", %s)\n"
            "    if _g:\n"
            "        return _g\n" % an)
    src = src[:mm2.start(1)] + ins2 + src[mm2.end(1):]
    print("  OK: %s 工具已接闸门（参数 %s）" % (tname, an))

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("tools.py syntax OK")
