#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy.py —— 板载 Agent 的**权限 / 禁忌层**

════════════════════════════════════════════════════════════════════
为什么需要这个
════════════════════════════════════════════════════════════════════
2026-09-28 事故：用户明确说"不要再播放了"，但 Agent **自己**用 shell
把音频服务拉起来、做了自检、从喇叭放出了声音 —— 两次。

根因不是"模型不听话"，而是：
    Agent 有不受限的 root shell，而且**没有"该不该做"这个概念**。
    用户的要求只存在于对话里，没有变成 Agent 能看到的约束。

用户对这件事的定性：「这是比声音大严重得多的问题」。

════════════════════════════════════════════════════════════════════
设计
════════════════════════════════════════════════════════════════════
三种判定：
    allow    —— 直接执行（只读命令）
    deny     —— 直接拒绝（危险命令 / 静音期放音）
    confirm  —— 登记到"待批准队列"，返回给模型让它去问用户；
                用户批准后，**同一条命令**在有效期内可直接执行

关键点：批准是**按具体动作**给的，不是给"权限"。批准一条 `systemctl
restart zynq-audio` 不等于以后所有 systemctl 都能跑。

策略文件 /etc/xiaobai-policy.json 可以覆盖默认规则（不用改代码）。
"""
import hashlib
import json
import os
import re
import threading
import time

POLICY_FILE = "/etc/xiaobai-policy.json"
SILENT_FLAG = "/etc/zynq-silent"
APPROVAL_TTL = 300.0            # 批准后 5 分钟内有效
PENDING_MAX = 20                # 队列上限，防刷

# ────────────────────────────────── 默认策略
DEFAULTS = {
    # 命中即拒绝（不看别的）
    "deny": [
        r"rm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+/\s*$",
        r"rm\s+-rf\s+/(\s|$)",
        r"\bmkfs(\.|\s)",
        r"\bdd\b[^|]*of\s*=\s*/dev/[sh]d",
        r":\s*\(\s*\)\s*\{.*\}\s*;\s*:",          # fork bomb
        r">\s*/dev/[sh]d[a-z]",
        r"\bchmod\s+(-R\s+)?777\s+/(\s|$)",
        r"\bsudo\s+rm\s+-rf\s+/(\s|$)",
    ],
    # 静音锁生效时，这些也直接拒绝
    "deny_when_silent": [
        r"\bsystemctl\s+(start|restart|enable|unmask)\s+zynq-audio",
        r"\bmv\b.*zynq-audio\.service",
        r"\bpython3?\b.*(loopback_proof|matrix_vol|selftest|play_|chime|beep)",
        r"/stop\b", r"/play\b", r"/matrix\b", r"/selftest\b",
    ],
    # 需要用户确认
    "confirm": [
        r"\bsystemctl\b", r"\bservice\b",
        r"\bapt(-get)?\b", r"\bpip3?\b", r"\bnpm\b",
        r"\brm\b", r"\bmv\b", r"\bdd\b", r"\btruncate\b",
        r"\bchmod\b", r"\bchown\b", r"\bmkdir\b", r"\btouch\b",
        r"\breboot\b", r"\bshutdown\b", r"\bhalt\b", r"\bpoweroff\b",
        r"\bi2cset\b", r"\bi2cdump\b",
        r">\s*/(etc|boot|root|usr|bin|sbin|lib)/",
        r"\bkill(all)?\b", r"\bpkill\b",
    ],
    # 只读白名单（前缀匹配，命中即放行，不看 confirm）
    "readonly": [
        "ls", "cat", "head", "tail", "wc", "grep", "egrep", "find", "which",
        "ps", "df", "du", "free", "uptime", "uname", "hostname", "date",
        "whoami", "id", "env", "printenv", "echo", "pwd", "file", "stat",
        "systemctl is-active", "systemctl status", "systemctl is-enabled",
        "systemctl list-units", "journalctl", "dmesg", "ip a", "ip addr",
        "ip route", "ifconfig", "iwconfig", "iwgetid", "v4l2-ctl --list",
        "vcgencmd", "lsblk", "mount", "top -bn1", "cat /proc", "cat /sys",
        "python3 -c", "python3 --version", "curl -s http://127.0.0.1",
    ],
    # 写这些目录要确认
    "protected_write_paths": [
        "/etc", "/boot", "/root", "/usr", "/bin", "/sbin", "/lib",
        "/var/lib", "/home/zynq/agent", "/home/zynq/ui",
    ],
}


def _load():
    d = json.loads(json.dumps(DEFAULTS))     # deep copy
    try:
        with open(POLICY_FILE, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            for k, v in user.items():
                if isinstance(v, list) and k in d:
                    d[k] = d[k] + v          # 用户规则是**追加**，不是覆盖
                else:
                    d[k] = v
    except Exception:
        pass
    return d


_cfg = None
_cfg_t = 0.0


def cfg():
    global _cfg, _cfg_t
    if _cfg is None or time.time() - _cfg_t > 30:
        _cfg = _load()
        _cfg_t = time.time()
    return _cfg


def silent():
    return os.path.exists(SILENT_FLAG)


# ────────────────────────────────── 判定
def _split_compound(cmd):
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
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch in ";|&" or cmd[i:i + 2] in ("&&", "||"):
            # ★ 坑：`2>&1` 里的 `&` 不是命令分隔符（它复制文件描述符）。
            #   判据：`&` 前一个字符是 `>`，或后一个字符是数字 -> 不是分隔符。
            if ch == "&" and (cmd[i - 1:i] == ">" or cmd[i + 1:i + 2].isdigit()):
                cur += ch
                i += 1
                continue
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
        low = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+", "", low)
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
    # ★ 坑：`2>/dev/null` 是无害的（丢弃 stderr），不能当成危险重定向。
    #   system 工具的命令里就有 `cat /sys/.../temp 2>/dev/null`，
    #   第一版正则把任何 `>` 都拉高到 confirm，结果 system 工具用不了。
    #   只把**重定向到非 /dev/null** 的算危险。
    redirects = re.findall(r"\d?&?>{1,2}\s*(\S+)", c)
    # 无害目标：/dev/null（丢弃）+ &1/&2（复制文件描述符）
    bad_redir = [t for t in redirects
                 if not (t.startswith("/dev/null") or t in ("&1", "&2"))]
    if bad_redir or "$(" in c or "`" in c:
        forced_confirm = "含重定向或命令替换（-> %s）" % (
            bad_redir[0] if bad_redir else "命令替换")
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


def classify_write(path):
    """写文件：受保护目录要确认"""
    p = os.path.abspath(path or "")
    for d in cfg()["protected_write_paths"]:
        if p == d or p.startswith(d.rstrip("/") + "/"):
            return "confirm", "写入受保护目录 %s" % d
    return "allow", "普通路径"


# ────────────────────────────────── 待批准队列
_lock = threading.Lock()
_pending = []          # [{id, kind, payload, reason, ts}]
_approved = {}         # key -> 过期时间


def _key(kind, payload):
    return hashlib.sha1(("%s|%s" % (kind, payload)).encode()).hexdigest()[:16]


def is_approved(kind, payload):
    k = _key(kind, payload)
    exp = _approved.get(k)
    if exp and exp > time.time():
        return True
    _approved.pop(k, None)
    return False


def request(kind, payload, reason):
    """登记待批准动作，返回 id。同一个动作只登记一次。"""
    k = _key(kind, payload)
    with _lock:
        for it in _pending:
            if it["key"] == k:
                return it["id"]
        if len(_pending) >= PENDING_MAX:
            _pending.pop(0)
        rid = "%s-%d" % (k[:6], int(time.time()) % 100000)
        _pending.append({"id": rid, "key": k, "kind": kind,
                         "payload": payload, "reason": reason,
                         "ts": time.time()})
        return rid


def list_pending():
    with _lock:
        now = time.time()
        return [dict(it, age=round(now - it["ts"], 1)) for it in _pending]


def resolve(rid, ok):
    """用户裁决。ok=True 则把该动作加入有效期白名单。"""
    with _lock:
        for i, it in enumerate(_pending):
            if it["id"] == rid:
                _pending.pop(i)
                if ok:
                    _approved[it["key"]] = time.time() + APPROVAL_TTL
                return it
    return None


def clear_pending():
    with _lock:
        n = len(_pending)
        _pending[:] = []
        return n


def describe():
    C = cfg()
    return {
        "silent": silent(),
        "policy_file": POLICY_FILE,
        "readonly_rules": len(C["readonly"]),
        "confirm_rules": len(C["confirm"]),
        "deny_rules": len(C["deny"]) + len(C["deny_when_silent"]),
        "pending": len(list_pending()),
        "approved_active": sum(1 for e in _approved.values() if e > time.time()),
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("静音锁:", silent())
    print("策略:", describe())
    print()
    for c in ("ls /home/zynq", "cat /proc/meminfo", "free -m",
              "systemctl is-active zynq-audio",
              "systemctl restart zynq-audio",
              "sudo systemctl start zynq-audio",
              "rm -rf /tmp/x", "rm -rf /", "apt-get install -y foo",
              "echo hi > /etc/foo", "python3 loopback_proof.py"):
        d, r = classify_shell(c)
        print("  %-6s %-38s %s" % (d, c, r))
