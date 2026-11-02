#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""test_cloud_api_http.py —— 把云协同服务真跑起来，端到端测所有端点

自检（cloud_api.py --selftest）只测各模块能不能用；这个脚本测 **HTTP 层**：
  · 路由对不对
  · 鉴权有没有生效（token 错了要 401，而且不能是 HTML 错误页）
  · 响应格式是不是约定的 JSON
  · ★ 分块上传能不能真传上去并校验 md5
  · ★ Range 下载能不能断点续传
  · ★ 写操作有没有记审计
  · ★ 中文/特殊字符的 URL 要能处理

════════════════════════════════════════════════════════════════════
★ 测试环境怎么模拟"板子"
════════════════════════════════════════════════════════════════════
板子是 Linux，路径白名单是 POSIX 风格（/home/zynq/...）。
但开发机是 Windows，os.path 的行为不一样（realpath("/home/..") 会变成 D:\home\..）。
所以测试版服务里加了一层映射：
    /data/...  ->  真实的 Windows 临时目录
白名单判断照常用 POSIX 语义（和板子上完全一致），
只有真正碰文件系统的时候才翻译成 Windows 路径。

这样测出来的路由/鉴权/上传/下载逻辑，和板子上的行为是一样的。

用法:
    python test_cloud_api_http.py
"""
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
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


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
TOKEN = "testtoken123"
BASE = "http://127.0.0.1:%d" % PORT
POSIX_ROOT = "/data"

TMP = tempfile.mkdtemp(prefix="cloudapi_")
WORK = os.path.join(TMP, "work")          # /data 映射到这里
os.makedirs(WORK, exist_ok=True)
CONF = os.path.join(TMP, "conf.json")
open(CONF, "w", encoding="utf-8").write(json.dumps({
    "token": TOKEN, "port": PORT, "enable_write": True, "discover_port": 0}))

# ---- 生成"测试版"服务 ----
src = open(os.path.join(HERE, "cloud_api.py"), encoding="utf-8").read()
patched = src.replace('CONF_FILE = "/etc/xiaobai-cloud.json"',
                      'CONF_FILE = r"%s"' % CONF)
patched = patched.replace('ALLOW_ROOTS = [',
                          'ALLOW_ROOTS = [\n    r"%s",' % POSIX_ROOT)
patched = patched.replace('AUDIT_FILE = "/var/lib/xiaobai-cloud/audit.jsonl"',
                          'AUDIT_FILE = r"%s"' % os.path.join(TMP, "audit.jsonl"))
patched = patched.replace('UPLOAD_DIR = "/var/lib/xiaobai-cloud/uploads"',
                          'UPLOAD_DIR = r"%s"' % os.path.join(TMP, "uploads"))

# 在 path_ok 之后插入映射层（测试专用）
marker = "\n\n# ---------------------------------------------------------------- 业务处理"
mapping = '''

# ══════════════════════════════════════════════════════════════════
#  ★ 测试专用：把 POSIX 路径映射到真实的 Windows 临时目录
#    白名单判断走 POSIX 语义（和板子一致），只有碰文件系统时才翻译。
# ══════════════════════════════════════════════════════════════════
_ORIG_PATH_OK = path_ok
_TEST_ROOT = r"%s"
_TEST_POSIX = r"%s"


def path_ok(path, write=False):        # noqa: F811
    ok2, rp, why = _ORIG_PATH_OK(path, write)
    if not ok2:
        return ok2, rp, why
    if rp == _TEST_POSIX or rp.startswith(_TEST_POSIX + "/"):
        tail = rp[len(_TEST_POSIX):].replace("/", "\\\\")
        rp = _TEST_ROOT + tail
    return ok2, rp, why

''' % (WORK, POSIX_ROOT)
patched = patched.replace(marker, mapping + marker)

TESTPY = os.path.join(TMP, "cloud_api_test.py")
open(TESTPY, "w", encoding="utf-8").write(patched)


# ---- 请求助手 ----
def req(method, path, body=None, token=TOKEN, raw=False, headers=None):
    # ★ 中文/空格等必须 percent-encode（这也是给客户端的契约）
    if "?" in path:
        p, q = path.split("?", 1)
        path = p + "?" + urllib.parse.quote(q, safe="=&/")
    else:
        path = urllib.parse.quote(path, safe="/")
    url = BASE + path
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            b = resp.read()
            return resp.status, (b if raw else json.loads(b.decode()))
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b.decode())
        except Exception:
            return e.code, b.decode(errors="replace")[:200]


print("=" * 78)
print(" 云协同 HTTP 端到端测试")
print("=" * 78)
print(" 端口 %d" % PORT)
print(" POSIX 白名单 %s  ->  %s" % (POSIX_ROOT, WORK))
print()

proc = subprocess.Popen([sys.executable, TESTPY, "--port", str(PORT),
                         "--no-discover"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        cwd=HERE,
                        # ★ 让服务从本仓库目录 import agent（板子上是 /home/zynq）
                        env={**os.environ, "XIAOBAI_AGENT_DIR": HERE})
up = False
for _ in range(40):
    time.sleep(0.25)
    try:
        s, d = req("GET", "/health", token=None)
        if s == 200:
            up = True
            break
    except Exception:
        pass

chk(up, "服务起来了")
if not up:
    out = proc.stdout.read().decode(errors="replace")[:1200]
    print("   服务输出:\n" + out)
    proc.kill()
    sys.exit(1)

try:
    # ══════════════════════════════════════════════════ 鉴权
    print("\n【1】鉴权")
    s, d = req("GET", "/health", token=None)
    chk(s == 200 and d.get("ok"), "/health 不需要 token", "HTTP %d" % s)
    s, d = req("GET", "/info", token=None)
    chk(s == 401 and d.get("ok") is False, "不带 token -> 401",
        "HTTP %d %s" % (s, d.get("error")))
    chk(isinstance(d, dict), "401 也是 JSON（不是 HTML 错误页）")
    s, d = req("GET", "/info?token=" + TOKEN, token=None)
    chk(s == 200, "URL 参数带 token 也认", "HTTP %d" % s)
    s, d = req("GET", "/info", token="wrong-token-xyz")
    chk(s == 401, "错 token -> 401", "HTTP %d" % s)
    # ★ 重要契约：HTTP 头只能放 latin-1，token 必须是 ASCII。
    #   这里用中文 token 会直接报 UnicodeEncodeError（客户端也一样）。
    #   所以下面这条是"文档性"检查 —— 确认服务端不会因为奇怪 token 崩掉。
    s, d = req("GET", "/info?token=%E9%94%99%E7%9A%84", token="")
    chk(s == 401, "URL 里带非 ASCII 的错误 token -> 401（不崩）",
        "HTTP %d" % s)

    # ══════════════════════════════════════════════════ 信息
    print("\n【2】信息接口")
    s, d = req("GET", "/info")
    chk(s == 200 and d.get("ok"), "/info 正常")
    for f in ("temperature_c", "services", "bitstream", "hostname"):
        chk(f in d, "有 %s" % f)

    # ══════════════════════════════════════════════════ 文件
    print("\n【3】文件接口")
    s, d = req("GET", "/fs/list?path=" + POSIX_ROOT)
    chk(s == 200 and d.get("ok"), "/fs/list 正常", str(d.get("error", ""))[:50])
    s, d = req("GET", "/fs/list?path=/etc")
    chk(s == 200 and not d.get("ok"), "列 /etc 被拒", d.get("error", "")[:40])
    s, d = req("GET", "/fs/list?path=相对路径")
    chk(s == 200 and not d.get("ok"), "相对路径被拒")

    print("\n【4】★ 分块上传（真传 3MB，验 md5）")
    payload = os.urandom(3 * 1024 * 1024)
    want_md5 = hashlib.md5(payload).hexdigest()
    target = POSIX_ROOT + "/uploaded.bin"
    s, d = req("POST", "/fs/upload/begin",
               {"path": target, "size": len(payload), "md5": want_md5})
    chk(s == 200 and d.get("ok"), "upload/begin 成功", str(d)[:70])
    uid = d.get("upload_id")
    chunk = 1 << 20
    got = 0
    for off in range(0, len(payload), chunk):
        piece = payload[off:off + chunk]
        s, d = req("POST", "/fs/upload/chunk",
                   {"upload_id": uid, "offset": off,
                    "data": base64.b64encode(piece).decode()})
        if not d.get("ok"):
            print("       块 %d 失败: %s" % (off, d.get("error")))
            break
        got = d.get("received", got)
    chk(got == len(payload), "所有块都收到", "%d / %d" % (got, len(payload)))
    s, d = req("POST", "/fs/upload/end", {"upload_id": uid})
    chk(s == 200 and d.get("ok"), "upload/end 成功（md5 校验过）", str(d)[:80])
    real_target = os.path.join(WORK, "uploaded.bin")
    chk(os.path.exists(real_target), "文件真的落盘了")
    if os.path.exists(real_target):
        got_md5 = hashlib.md5(open(real_target, "rb").read()).hexdigest()
        chk(got_md5 == want_md5, "落盘内容与上传一致")

    print("\n【5】★ md5 不符必须拒绝")
    s, d = req("POST", "/fs/upload/begin",
               {"path": POSIX_ROOT + "/bad.bin", "size": 10, "md5": "0" * 32})
    uid2 = d.get("upload_id")
    req("POST", "/fs/upload/chunk",
        {"upload_id": uid2, "offset": 0,
         "data": base64.b64encode(b"0123456789").decode()})
    s, d = req("POST", "/fs/upload/end", {"upload_id": uid2})
    chk(s == 200 and not d.get("ok"), "md5 不符被拒", d.get("error", "")[:40])
    chk(d.get("code") == "md5_mismatch", "错误码是 md5_mismatch",
        str(d.get("code")))
    chk(not os.path.exists(os.path.join(WORK, "bad.bin")),
        "★ 校验失败的文件没有落盘")

    print("\n【6】下载 + Range（断点续传）")
    s, body = req("GET", "/fs/download?path=" + target, raw=True)
    chk(s == 200 and isinstance(body, bytes) and len(body) == len(payload),
        "整文件下载", "%d 字节" % (len(body) if isinstance(body, bytes) else -1))
    s, body = req("GET", "/fs/download?path=" + target, raw=True,
                  headers={"Range": "bytes=1048576-"})
    chk(s == 206, "Range 返回 206", "HTTP %d" % s)
    chk(isinstance(body, bytes) and len(body) == len(payload) - 1048576,
        "Range 内容长度正确",
        "%d" % (len(body) if isinstance(body, bytes) else -1))

    print("\n【7】删除 + 审计")
    s, d = req("POST", "/fs/delete", {"path": target})
    chk(s == 200 and d.get("ok"), "删除成功", str(d)[:60])
    chk(not os.path.exists(real_target), "文件真的没了")
    af = os.path.join(TMP, "audit.jsonl")
    chk(os.path.exists(af), "审计文件生成了")
    if os.path.exists(af):
        txt = open(af, encoding="utf-8").read()
        for a in ("fs_delete", "upload_begin", "upload_end"):
            chk(a in txt, "审计里有 %s" % a)

    # ══════════════════════════════════════════════════ 硬件
    print("\n【8】硬件接口")
    s, d = req("GET", "/hw/regs?base=scope_0&offset=0x34")
    chk(s == 200 and "ok" in d, "/hw/regs 返回约定格式",
        "ok=%s（板子不在时为 false，正确）" % d.get("ok"))
    s, d = req("GET", "/hw/thermal")
    chk(s == 200 and d.get("ok"), "/hw/thermal 正常")
    chk("thresholds" in d, "有 thresholds")
    s, d = req("GET", "/hw/services")
    chk(s == 200 and d.get("ok"), "/hw/services 正常")
    s, d = req("GET", "/hw/logs?name=不存在的日志")
    chk(s == 200 and not d.get("ok"), "不存在的日志名被拒")
    s, d = req("POST", "/hw/service", {"name": "zynq-agent", "action": "stop"})
    chk(s == 200 and not d.get("ok"), "★ 停 zynq-agent 被拒（防失联）",
        d.get("error", "")[:50])
    s, d = req("POST", "/hw/service", {"name": "不存在的服务", "action": "start"})
    chk(s == 200 and not d.get("ok"), "不认识的服务被拒")
    s, d = req("POST", "/hw/reg", {"base": "不存在的ip", "offset": "0x0",
                                   "value": "1"})
    chk(s == 200 and not d.get("ok"), "写不认识的 base 被拒")

    print("\n【9】变更历史 + 回滚")
    s, d = req("GET", "/hw/changes?limit=5")
    chk(s == 200 and d.get("ok"), "/hw/changes 正常")
    chk("changes" in d and isinstance(d["changes"], list), "有 changes 数组")
    s, d = req("GET", "/hw/changes/nonexistent_id")
    chk(s == 200 and not d.get("ok"), "查不存在的变更单给出明确错误",
        d.get("error", "")[:40])
    s, d = req("POST", "/hw/rollback", {"id": "nonexistent_id"})
    chk(s == 200 and not d.get("ok"), "回滚不存在的 id 被拒")

    print("\n【10】构建任务")
    s, d = req("GET", "/fpga/builds")
    chk(s == 200 and d.get("ok"), "/fpga/builds 正常")
    s, d = req("GET", "/fpga/build/nonexistent_id")
    chk(s == 200 and not d.get("ok"), "查不存在的构建任务给出错误")

    print("\n【11】对话与模型配置")
    s, d = req("GET", "/chat/sessions")
    chk(s == 200 and d.get("ok"), "/chat/sessions 正常")
    s, d = req("GET", "/llm/config")
    chk(s == 200 and d.get("ok"), "/llm/config 正常")
    chk("mode" in d, "有 mode 字段", str(d.get("mode")))
    s, d = req("POST", "/llm/config", {"mode": "不合法"})
    chk(s == 200 and not d.get("ok"), "不合法的 mode 被拒")

    print("\n【12】容错")
    s, d = req("GET", "/nonexistent")
    chk(s == 404 and d.get("ok") is False, "未知接口 404 + JSON")
    s, d = req("POST", "/nonexistent", {})
    chk(s == 404 and d.get("ok") is False, "未知 POST 404 + JSON")
    s, d = req("POST", "/fs/delete", {"path": "/etc/passwd"})
    chk(s == 200 and not d.get("ok"), "★ 删系统文件被拒", d.get("error", "")[:40])

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print()
print("=" * 78)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 78)
print()
print("★ 客户端（EXE/APK）照这些调用实现：")
print("    GET  /health                        存活（不需要 token）")
print("    GET  /info                          板子信息")
print("    GET  /fs/list | /fs/stat | /fs/download")
print("    POST /fs/upload/begin | chunk | end 分块上传")
print("    POST /fs/delete | /fs/mkdir")
print("    GET  /hw/regs | thermal | services | logs")
print("    POST /hw/reg | /hw/service | /hw/rollback")
print("    GET  /hw/changes | /hw/changes/<id>")
print("    POST /chat   GET /chat/sessions   GET/POST /llm/config")
print("    POST /fpga/build   GET /fpga/build/<id> | /fpga/builds")

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
