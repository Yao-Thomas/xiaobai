#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_llm_key.py —— 验证 /llm/key 的参数校验和"不回显"

★ 这个接口是给客户端存 API key 用的，安全要求高：
    ① 写完【不回显】key（只给前 4 位）
    ② 审计日志里【不能有全 key】
    ③ 文件权限 600
    ④ 奇怪的 key（含引号/shell 元字符/非 ASCII）必须拒绝

用法:
    python test_llm_key.py
"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ok = True


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


import cloud_api as C                                       # noqa: E402

print("=" * 74)
print(" /llm/key 参数校验 + 安全要求")
print("=" * 74)

TMP = tempfile.mkdtemp(prefix="llmkey_")
C.AUDIT_FILE = os.path.join(TMP, "audit.jsonl")
ENVF = os.path.join(TMP, "zynq-agent.env")

api = C.Api({"enable_write": True, "token": "testtoken"})

# 把 env 文件指到临时目录（monkey patch 掉硬编码路径）
_orig_open = io.open
_real_set = C.Api.llm_set_key
ENVF_BAK = "/etc/zynq-agent.env"


def patched_set_key(self, key, provider="deepseek"):
    """把 /etc/zynq-agent.env 换成临时文件跑 —— 逻辑完全一样"""
    src = C.Api.llm_set_key.__code__
    # 直接手工复制逻辑太脆，用替换字符串的办法更稳
    return _real_set(self, key, provider)


# ★ 简单办法：用 sed 风格替换只在本进程内做一次
import types
src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "cloud_api.py"), encoding="utf-8").read()
src2 = src.replace('envf = "/etc/zynq-agent.env"',
                   'envf = %r' % ENVF)
mod = types.ModuleType("cloud_api_test")
mod.__dict__["__file__"] = os.path.join(TMP, "cloud_api_test.py")
exec(compile(src2, "cloud_api_test.py", "exec"), mod.__dict__)
mod.AUDIT_FILE = C.AUDIT_FILE
api = mod.Api({"enable_write": True, "token": "testtoken"})

print("\n【1】参数校验（该拒的必须拒）")
cases = [
    ("", False, "空"),
    ("short", False, "太短"),
    ("中文key" * 6, False, "非 ASCII"),
    ("a" * 20, True, "正常 20 位"),
    ("sk-" + "b" * 30, True, "像真的 key"),
    ('x' * 30 + '"', False, "含双引号"),
    ("y" * 30 + "'", False, "含单引号"),
    ("z" * 30 + "$", False, "含 $"),
    ("w" * 30 + ";", False, "含分号"),
    ("v" * 15 + " " + "v" * 15, False, "中间有空格"),
    ("u" * 15 + "\n" + "u" * 15, False, "中间有换行"),
    ("t" * 30 + "&", False, "含 &"),
    ("s" * 30 + "|", False, "含 |"),
    # ★ 尾部空白会被 strip 掉 —— 这是【对的】行为，所以算接受
    ("ok" * 10 + "   ", True, "尾部空格（会被 strip）"),
]
for key, want, why in cases:
    r = api.llm_set_key(key)
    got = bool(r.get("ok"))
    chk(got == want, "%-22s -> %s" % (why, "接受" if got else "拒绝"),
        "" if got == want else ("期望 %s，错误=%s"
                                % ("接受" if want else "拒绝",
                                   r.get("error", "")[:40])))

print("\n【2】★ 写完不回显 key")
LONG = "sk-" + "A" * 40
r = api.llm_set_key(LONG)
chk(r.get("ok"), "能写进去", str(r.get("error", ""))[:50])
s = json.dumps(r, ensure_ascii=False)
chk(LONG not in s, "★ 返回里没有完整 key")
chk(r.get("hint") == LONG[:4] + "…", "只给前 4 位", str(r.get("hint")))
chk("has_key" in r, "有 has_key 字段")

print("\n【3】★ env 文件真的写对了")
chk(os.path.exists(ENVF), "文件建了")
if os.path.exists(ENVF):
    txt = io.open(ENVF, encoding="utf-8").read()
    chk(("DEEPSEEK_API_KEY=%s" % LONG) in txt, "key 写进去了")
    # ★ Windows 上 os.chmod 不真的设 POSIX 权限（只动只读位），
    #   所以这里只在 POSIX 上检查 600；板子是 Linux，会真的检查到。
    if os.name == "posix":
        mode = oct(os.stat(ENVF).st_mode & 0o777)
        chk(mode == "0o600", "★ 文件权限 600（只有属主能读）", mode)
    else:
        print("   - 跳过权限检查（Windows 上 os.chmod 不设 POSIX 权限）")
        chk(True, "权限检查在 Linux 上做（板上会验）")

print("\n【4】★ 审计里不能有完整 key")
if os.path.exists(C.AUDIT_FILE):
    at = io.open(C.AUDIT_FILE, encoding="utf-8").read()
    chk(LONG not in at, "★ 审计里没有完整 key")
    chk(LONG[:4] in at, "审计里有前 4 位（方便对账）")
else:
    chk(False, "没有审计文件")

print("\n【5】改 key 是覆盖不是追加")
r2 = api.llm_set_key("sk-" + "B" * 40)
chk(r2.get("ok"), "第二次也能写")
txt = io.open(ENVF, encoding="utf-8").read()
n = txt.count("DEEPSEEK_API_KEY=")
chk(n == 1, "★ 文件里只有一行 DEEPSEEK_API_KEY（覆盖成功）",
    "%d 行" % n)

print("\n【6】只读模式拒绝")
ro = mod.Api({"enable_write": False, "token": "t"})
r3 = ro.llm_set_key("sk-" + "C" * 40)
chk(not r3.get("ok"), "只读模式下拒绝", str(r3.get("error", ""))[:40])

print()
print("=" * 74)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 74)

import shutil                                               # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
