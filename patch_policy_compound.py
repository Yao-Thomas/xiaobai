#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_policy_compound.py —— 让权限层认**复合命令**

═══ 问题 ═══
工具审计（22 轮）发现 `system` 工具被判成"需要用户批准"：

    system  ->  【需要用户批准】不在只读白名单里

但 `system` 是**纯只读**的状态查询（CPU/内存/磁盘/温度/网络/负载）。
它内部拼的命令是复合的：

    uptime; echo ---; free -m | head -3; echo ---; df -h / | tail -1; ...

而原来的 classify_shell 只做**整串前缀匹配** -> 认不出来 -> 落到 confirm。
后果：Agent 每次想看系统状态都得申请批准，演示时会被烦死。

═══ 修法 ═══
把命令按 `;` `&&` `||` `|` 拆成组件，**逐段分类**：

    全段 allow          -> allow
    任一段 deny         -> deny
    其余（含 confirm）  -> confirm

并且：
  * **重定向 `>` / `>>` 一律拉高到 confirm**（哪怕左边是只读命令）
  * 命令替换 `$(...)` / 反引号 内含写操作也拉高
  * 拆不出来（引号不闭合等）就保守判 confirm
"""
import io
import sys

P = "agent/policy.py"
src = io.open(P, encoding="utf-8").read()

if "_split_compound" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''def classify_shell(cmd):
    """返回 (决定, 原因)。决定 ∈ allow / deny / confirm"""
    c = (cmd or "").strip()
    if not c:
        return "deny", "空命令"
    C = cfg()

    for p in C["deny"]:
        if re.search(p, c, re.I):
            return "deny", "命中禁止规则: %s" % p

    if silent():
        for p in C["deny_when_silent"]:
            if re.search(p, c, re.I):
                return "deny", ("【静音锁生效】用户要求在他同意前不许出声，"
                                "这条命令会导致放音，已拒绝")

    # 只读白名单
    # ★ 坑：str.lstrip("sudo ") 不是"去掉 sudo 前缀"，而是**去掉字符集里
    #   任意字符** —— "systemctl is-active".lstrip("sudo ") 会变成
    #   "ystemctl is-active"，前缀匹配就废了。必须显式判断前缀。
    low = c
    while low.startswith("sudo "):
        low = low[5:].strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", low):      # 去掉 VAR=val 前缀
        low = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*=\\S*\\s+", "", low)
    for pre in C["readonly"]:
        if low.startswith(pre):
            # 只读白名单里也不许夹带重定向/管道到写操作
            if ">" in c or ">>" in c:
                break
            return "allow", "只读命令"

    for p in C["confirm"]:
        if re.search(p, c, re.I):
            return "confirm", "该命令会修改系统状态"

    # 保守：不认识的也算需要确认
    return "confirm", "不在只读白名单里"
'''

NEW = '''def _split_compound(cmd):
    """把 `a; b && c | d` 拆成组件。

    ★ 只按**不在引号内**的分隔符拆。引号不闭合时返回 None（保守处理）。
    """
    parts, cur = [], ""
    q = None
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if q:
            if ch == q:
                q = None
            cur += ch
        elif ch in "\\"'":
            q = ch
            cur += ch
        elif ch in ";|&" or cmd[i:i + 2] in ("&&", "||"):
            if cur.strip():
                parts.append(cur.strip())
            cur = ""
            # 跳过连续的分隔符
            while i + 1 < n and cmd[i + 1] in ";|&":
                i += 1
        else:
            cur += ch
        i += 1
    if q:
        return None                 # 引号不闭合 -> 保守
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _classify_single(c, C, allow_silent_ok=True):
    """判断**单个**（不复合的）命令。返回 (决定, 原因)"""
    # 只读白名单
    # ★ 坑：str.lstrip("sudo ") 不是"去掉 sudo 前缀"，而是**去掉字符集里
    #   任意字符** —— "systemctl is-active".lstrip("sudo ") 会变成
    #   "ystemctl is-active"，前缀匹配就废了。必须显式判断前缀。
    low = c
    while low.startswith("sudo "):
        low = low[5:].strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", low):      # 去掉 VAR=val 前缀
        low = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*=\\S*\\s+", "", low)
    for pre in C["readonly"]:
        if low.startswith(pre):
            return "allow", "只读"
    for p in C["confirm"]:
        if re.search(p, c, re.I):
            return "confirm", "会修改系统状态"
    return "confirm", "不在只读白名单里"


def classify_shell(cmd):
    """返回 (决定, 原因)。决定 ∈ allow / deny / confirm

    ★ 支持复合命令：按 `;` `&&` `||` `|` 拆开**逐段判断**，
      全段只读才算只读。这样 `uptime; free -m; df -h` 能放行，
      而 `ls; rm -rf /` 仍然会被拒。
    """
    c = (cmd or "").strip()
    if not c:
        return "deny", "空命令"
    C = cfg()

    # ---- 整串先过禁止规则（这些要看全串，比如遍历整个 /）----
    for p in C["deny"]:
        if re.search(p, c, re.I):
            return "deny", "命中禁止规则: %s" % p

    if silent():
        for p in C["deny_when_silent"]:
            if re.search(p, c, re.I):
                return "deny", ("【静音锁生效】用户要求在他同意前不许出声，"
                                "这条命令会导致放音，已拒绝")

    # ---- 重定向 / 命令替换 -> 一律确认（哪怕左边只读）----
    if re.search(r"(^|[^>])>{1,2}\\s*\\S", c) or "$(" in c or "`" in c:
        # 但仍要给个明确原因；交给下面逐段判断后统一返回
        forced_confirm = "含重定向或命令替换"
    else:
        forced_confirm = None

    parts = _split_compound(c)
    if parts is None:
        return "confirm", "命令含不闭合的引号，无法安全解析"
    if not parts:
        return "confirm", "没解析出可执行部分"

    decs = [_classify_single(p, C) for p in parts]

    # 任一段 deny -> deny
    for d, r in decs:
        if d == "deny":
            return "deny", r

    if forced_confirm:
        return "confirm", forced_confirm

    # 全段 allow -> allow（★ 这就是 system 工具需要的）
    if all(d == "allow" for d, _ in decs):
        if len(parts) > 1:
            return "allow", "复合只读命令（%d 段全只读）" % len(parts)
        return "allow", "只读命令"

    # 有需要确认的段
    for p, (d, r) in zip(parts, decs):
        if d == "confirm":
            return "confirm", "%s：%s" % (r, p[:40])
    return "confirm", "不在只读白名单里"
'''

if OLD not in src:
    print("  [!] classify_shell 锚点没找到")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
