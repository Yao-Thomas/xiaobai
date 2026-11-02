#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_approve_api.py —— 给 main.py 加"待批准队列"的接口

    GET  /pending         看有哪些动作等着批准
    POST /approve         {"id":"..","ok":true}  同意 / 拒绝
    POST /pending/clear   清空队列

配套：tools.py 里的 _policy_gate 在 confirm 时会登记一条待批准动作，
用户在 UI 上点同意后，**同一条命令**在 5 分钟内可直接执行。
"""
import io
import sys

P = "agent/main.py"
src = io.open(P, encoding="utf-8").read()

if "/pending" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ── GET /pending（插在 /history 之后）
old_g = '''        if p.startswith("/history"):'''
new_g = '''        if p.startswith("/pending"):
            try:
                from . import policy
                self._send(200, {"ok": True, "policy": policy.describe(),
                                 "pending": policy.list_pending()})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if p.startswith("/history"):'''
assert old_g in src, "GET 锚点没找到"
src = src.replace(old_g, new_g, 1)

# ── POST /approve（插在 /session 之后）
old_p = '''        if self.path.startswith("/session"):'''
new_p = '''        if self.path.startswith("/approve"):
            try:
                from . import policy
                rid = data.get("id")
                ok = bool(data.get("ok", True))
                if rid in (None, "", "all"):
                    items = policy.list_pending()
                    n = 0
                    for it in items:
                        if policy.resolve(it["id"], ok):
                            n += 1
                    self._send(200, {"ok": True, "resolved": n, "approve": ok})
                    return
                it = policy.resolve(rid, ok)
                if it is None:
                    self._send(404, {"error": "没有这个待批准动作: %s" % rid})
                    return
                self._send(200, {"ok": True, "resolved": it, "approve": ok})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if self.path.startswith("/pending/clear"):
            try:
                from . import policy
                n = policy.clear_pending()
                self._send(200, {"ok": True, "cleared": n})
            except Exception as e:
                self._send(500, {"error": str(e)[:200]})
            return

        if self.path.startswith("/session"):'''
assert old_p in src, "POST 锚点没找到"
src = src.replace(old_p, new_p, 1)

# ── 接口文档补上
old_doc = '''        ("POST", "/session", '{"action":"reset"} 清空会话'),'''
new_doc = '''        ("POST", "/session", '{"action":"reset"} 清空会话'),
        ("GET", "/pending", "待批准的危险动作 + 权限层状态"),
        ("POST", "/approve", '{"id":"..","ok":true} 同意/拒绝（id=all 全部）'),
        ("POST", "/pending/clear", "清空待批准队列"),'''
assert old_doc in src, "文档锚点没找到"
src = src.replace(old_doc, new_doc, 1)

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
