#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_webui_api.py —— 验证网页用到的每个板子接口都能用

网页（webui/index.html）调这些接口：
    /health  /info
    /fs/list  /fs/download  /fs/delete  /fs/upload/{begin,chunk,end}
    /hw/regs  /hw/reg  /hw/services  /hw/service  /hw/logs  /hw/thermal
    /hw/changes  /hw/rollback
    /chat  /chat/sessions  /chat/history/<id>  /chat/export/<id>
    /tools  /tool  /fpga/builds  /fpga/build/<id>

按网页的调用方式全部打一遍，确认没有 404 / 500 / 格式不对。

★★ 设计：call() 【永远返回 dict】—— 连不上、返回 HTML、超时都包成
   {"ok": False, "error": "..."}。这样调用处不用到处判类型。
   （第一版返回 str 的时候，调用处 .get() 直接崩 —— 就是这么踩的）

用法:
    python test_webui_api.py --host 192.168.110.144 --token xxxx
    python test_webui_api.py                 # 自动从板子读 token
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ok = True


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


def call(host, token, path, method="GET", body=None, timeout=20):
    """★ 永远返回 dict —— 任何异常都包成 {"ok": False, "error": ...}

    ★★★ 拼 URL 的时候【一定要带端口】★★★
    踩过：host 只写 "192.168.110.144"，于是 URL 变成
        http://192.168.110.144/health      ← 打到 80 端口去了
    结果整个测试全是 "WinError 10061 连接被拒绝"，
    我还以为板子的 WiFi 有问题 —— 其实是自己漏了 :8768。
    """
    if not host:
        return {"ok": False, "error": "没填板子地址"}
    # 没写端口就补上 8768
    if ":" not in host.split("/")[0]:
        host = host + ":8768"
    url = "http://%s%s%s" % (host, path,
                             ("&" if "?" in path else "?") + "token="
                             + urllib.parse.quote(token or ""))
    data = json.dumps(body).encode() if body is not None else None
    h = {"Authorization": "Bearer " + (token or "")}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read()
            try:
                d = json.loads(b.decode())
                if isinstance(d, dict):
                    d.setdefault("_http", resp.status)
                    return d
                return {"ok": False, "_http": resp.status,
                        "error": "返回不是 JSON 对象"}
            except Exception:
                return {"ok": False, "_http": resp.status,
                        "error": "返回不是 JSON：%s" % b[:80]}
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            d = json.loads(b.decode())
            if isinstance(d, dict):
                d.setdefault("_http", e.code)
                return d
        except Exception:
            pass
        return {"ok": False, "_http": e.code,
                "error": "HTTP %d: %s" % (e.code, b[:80])}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def rejected(d):
    """★ 判断『确实被服务端拒绝了』—— 而不是『根本没连上』

    踩过：连不上时 d = {"ok": False, "error": "URLError..."}，
    于是所有 `chk(not d.get("ok"), "该被拒")` 全部【误判为通过】——
    网络断了反而"全过"，这种测试是自我安慰。
    ⇒ 必须要求真的收到了 HTTP 响应（_http 是数字）。
    """
    return (not d.get("ok")) and isinstance(d.get("_http"), int)


def board_token():
    """从板子上读 token（本机跑才用得上）"""
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "board.py"),
                            "cat /etc/xiaobai-cloud.json"],
                           stdout=subprocess.PIPE, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        for ln in out.split("\n"):
            if '"token"' in ln:
                return ln.split(":", 1)[1].strip().strip('",')
    except Exception:
        pass
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.110.144")
    ap.add_argument("--token", default="")
    a = ap.parse_args()

    host, token = a.host, a.token
    if not token:
        token = board_token()
    if not token:
        print("要 --token（板上 /etc/xiaobai-cloud.json 里的）")
        return 1

    print("=" * 74)
    print(" 网页用到的板子接口 · 端到端验证")
    print("=" * 74)
    print(" 板子: %s   token: %s…" % (host, token[:4]))
    print()

    print("【1】基本信息")
    d = call(host, token, "/health")
    chk(d.get("ok"), "/health（免 token）", str(d.get("error", ""))[:44])
    d = call(host, token, "/info")
    chk(d.get("ok"), "/info", str(d.get("error", ""))[:44])
    if d.get("ok"):
        chk("temperature_c" in d, "有温度", str(d.get("temperature_c")))
        chk("tools_count" in d, "有工具数", str(d.get("tools_count")))
        chk(isinstance(d.get("services"), dict), "有服务字典")
    print()

    print("【2】文件")
    d = call(host, token, "/fs/list?path=" + urllib.parse.quote("/home/zynq"))
    chk(d.get("ok"), "/fs/list 正常", str(d.get("error", ""))[:44])
    if d.get("ok"):
        chk(isinstance(d.get("items"), list), "有 items",
            "%d 项" % len(d.get("items") or []))
    d = call(host, token, "/fs/list?path=" + urllib.parse.quote("/etc"))
    chk(rejected(d), "/fs/list 越权被拒", str(d.get("error", ""))[:44])
    print()

    print("【3】硬件")
    for b in ("scope_0", "gpu_0", "cnn_conv_pool", "cnn_fc"):
        d = call(host, token, "/hw/regs?base=%s&offset=0x34" % b)
        good = d.get("ok") and d.get("regs")
        chk(good, "/hw/regs %s" % b,
            d["regs"][0]["value"] if good else str(d.get("error", ""))[:36])
    d = call(host, token, "/hw/thermal?limit=10")
    chk(d.get("ok"), "/hw/thermal", str(d.get("error", ""))[:44])
    if d.get("ok"):
        chk("history" in d, "有温度历史",
            "%d 条" % len(d.get("history") or []))
    d = call(host, token, "/hw/services")
    chk(d.get("ok"), "/hw/services", str(d.get("error", ""))[:44])
    d = call(host, token, "/hw/logs?name=desktop&lines=5")
    chk(d.get("ok"), "/hw/logs", str(d.get("error", ""))[:44])
    d = call(host, token, "/hw/service", "POST",
             {"name": "zynq-agent", "action": "stop"})
    chk(rejected(d), "★ 不许远程停 agent（防失联）",
        str(d.get("error", ""))[:44])
    d = call(host, token, "/hw/reg", "POST",
             {"base": "不存在的", "offset": "0x0", "value": "1"})
    chk(rejected(d), "写不认识的 base 被拒",
        str(d.get("error", ""))[:44])
    print()

    print("【4】变更历史")
    d = call(host, token, "/hw/changes?limit=20")
    chk(d.get("ok"), "/hw/changes", str(d.get("error", ""))[:44])
    if d.get("ok"):
        cs = d.get("changes") or []
        chk(isinstance(cs, list), "有 changes", "%d 条" % len(cs))
        if cs:
            for k in ("id", "ts", "kind", "detail", "rollbackable"):
                chk(k in cs[0], "每条有 %s" % k)
            chk(all(c.get("id") for c in cs), "★ 每条都有 id（没有 None）")
    d = call(host, token, "/hw/changes/nonexistent")
    chk(rejected(d), "查不存在的给出错误",
        str(d.get("error", ""))[:44])
    d = call(host, token, "/hw/rollback", "POST", {"id": "nonexistent"})
    chk(rejected(d), "回滚不存在的 id 被拒",
        str(d.get("error", ""))[:44])
    print()

    print("【5】对话")
    d = call(host, token, "/chat/sessions")
    chk(d.get("ok"), "/chat/sessions", str(d.get("error", ""))[:44])
    if d.get("ok"):
        chk("stats" in d, "有 stats",
            json.dumps(d.get("stats") or {}, ensure_ascii=False)[:70])
    d = call(host, token, "/chat/export/nonexistent")
    chk(rejected(d), "导出不存在的会话给出错误",
        str(d.get("error", ""))[:44])
    d = call(host, token, "/chat/history/nonexistent")
    chk(rejected(d), "查不存在的历史给出错误",
        str(d.get("error", ""))[:44])
    print()

    print("【6】工具")
    d = call(host, token, "/tools")
    chk(d.get("ok"), "/tools", str(d.get("error", ""))[:44])
    if d.get("ok"):
        ts = d.get("tools") or []
        names = [t.get("name") if isinstance(t, dict) else str(t) for t in ts]
        hw = [n for n in names if n.startswith("hw_")]
        chk(len(ts) > 0, "有工具", "%d 个" % len(ts))
        chk(len(hw) >= 16, "硬件工具 >= 16", "%d 个" % len(hw))
    d = call(host, token, "/tool", "POST",
             {"name": "hw_thermal", "args": {}})
    chk(d.get("ok"), "跑一个只读工具", str(d.get("result", ""))[:50])
    print()

    print("【7】构建任务")
    d = call(host, token, "/fpga/builds")
    chk(d.get("ok"), "/fpga/builds", str(d.get("error", ""))[:44])
    d = call(host, token, "/fpga/build/nonexistent")
    chk(rejected(d), "查不存在的构建给出错误",
        str(d.get("error", ""))[:44])
    print()

    print("【8】容错")
    d = call(host, token, "/nonexistent")
    chk(d.get("_http") == 404 and d.get("ok") is False,
        "未知接口 404 + JSON", "HTTP %s" % d.get("_http"))
    d = call(host, "wrong-token-xyz", "/info")
    chk(d.get("_http") == 401, "错 token -> 401", "HTTP %s" % d.get("_http"))
    d = call("", token, "/info")
    chk(not d.get("ok"), "空地址不崩", str(d.get("error", ""))[:30])
    print()

    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
