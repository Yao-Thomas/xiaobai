#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_fpga_loop.py —— 离线验证「agent 改 FPGA」的完整闭环（不需要板子）

这是这个项目的核心创新：**agent 能改自己的硬件**。
本脚本把整条链在 PC 上跑一遍（用本地任务目录代替板子）：

    ① hw_hdl_edit        改一个 RTL 文件（验证备份 + 语法检查 + 拒绝坏改动）
    ② hw_fpga_build      提交构建任务（写到本地 fpga_jobs）
    ③ fpga_build_daemon  本地模式取走任务、执行、写回结果
    ④ hw_fpga_build_status 读结果
    ⑤ hw_verify          跑回归清单（板子不在，会报硬检查失败 —— 这是对的）
    ⑥ hw_change_list     确认变更单都记下了

★ 关键要验的三件事：
   a) 改动**坏**的时候会被拦住（语法检查不通过就不写文件）
   b) 每次改动都**留了备份 + 变更单**（可追溯、可回滚）
   c) 构建任务是**异步**的（提交 → 守护执行 → 查结果），
      这样长任务（出流 20-50 分钟）不会把 agent 卡死

用法:
    python test_fpga_loop.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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


# ---- 用临时目录当"板子" ----
TMP = tempfile.mkdtemp(prefix="fpgaloop_")
JOBS = os.path.join(TMP, "fpga_jobs")
os.makedirs(JOBS, exist_ok=True)
os.environ["FPGA_JOBS_DIR"] = JOBS
os.environ["HWCHANGE_DIR"] = os.path.join(TMP, "hwchange")

from agent import tools as T                                     # noqa: E402
from agent import hw_tools as HW                                 # noqa: E402
from agent import policy as POL                                  # noqa: E402
import agent.hw_change as HC                                     # noqa: E402


def pre_approve(kind, payload):
    """先在权限层把某个动作批准掉

    ★ 为什么需要：hw_fpga_build / hw_hdl_edit 这类操作会被 policy 闸门拦住
      要求"用户批准"。这是**安全设计正确的行为**，不是 bug。
      测试里模拟"用户点了同意"：先 request 拿 id，再 resolve(id, True)。
    """
    rid = POL.request(kind, payload, "离线测试自动批准")
    POL.resolve(rid, True)
    return rid

# 把变更单也指到临时目录
HC.CHANGE_DIR = os.environ["HWCHANGE_DIR"]
HC.CHANGE_FILE = os.path.join(HC.CHANGE_DIR, "changes.jsonl")
HC.SNAPSHOT_DIR = os.path.join(HC.CHANGE_DIR, "snapshots")
HW.CHANGE_DIR = HC.CHANGE_DIR
HW.CHANGE_FILE = HC.CHANGE_FILE

RTL = os.path.join(TMP, "scope_cap.v")
open(RTL, "w", encoding="utf-8").write("""// scope_cap.v —— 示波器采集（测试用）
module scope_cap (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,
    output reg  [7:0]  sample
);
    reg [7:0] cnt;
    always @(posedge clk) begin
        if (!rst_n) begin
            cnt    <= 8'd0;
            sample <= 8'd0;
        end else if (tick) begin
            cnt    <= cnt + 8'd1;
            sample <= cnt;
        end
    end
endmodule
""")

print("=" * 78)
print(" 「agent 改 FPGA」闭环离线验证")
print("=" * 78)
print(" 临时目录: %s" % TMP)
print()

# ══════════════════════════════════════════════════════════════ ①
print("【①】hw_hdl_edit —— 正常情况下改一个 RTL 文件")
pre_approve("write", "hdl_edit %s: 加外部采样有效输入（示波器 V2 的第一步）" % RTL)
r = T.call("hw_hdl_edit", {
    "file": RTL,
    "old": "    output reg  [7:0]  sample\n);",
    "new": "    output reg  [7:0]  sample,\n    input  wire        ext_valid\n);",
    "note": "加外部采样有效输入（示波器 V2 的第一步）",
}, {})
print("   " + r.replace("\n", "\n   ")[:400])
chk("已改" in r, "改动应用成功")
chk("备份" in r, "留了备份")
new_src = open(RTL, encoding="utf-8").read()
chk("ext_valid" in new_src, "文件里真的有 ext_valid 了")
chk(len([f for f in os.listdir(TMP) if f.startswith("scope_cap.v.bak_hdl_")]) >= 1,
    "备份文件存在")

# ══════════════════════════════════════════════════════════════ ②
print("\n【②】★ 关键：坏改动必须被拦住")
before = open(RTL, encoding="utf-8").read()
pre_approve("write", "hdl_edit %s: 故意写坏（begin 不配对）" % RTL)
r2 = T.call("hw_hdl_edit", {
    "file": RTL,
    "old": "    reg [7:0] cnt;",
    "new": "    reg [7:0] cnt;\n    always @(posedge clk) begin",  # 故意加一个没配对的 begin
    "note": "故意写坏（begin 不配对）",
}, {})
print("   " + r2.replace("\n", "\n   ")[:300])
chk("没通过" in r2 or "放弃" in r2,
    "★ 语法检查拦住了坏改动")
chk(open(RTL, encoding="utf-8").read() == before,
    "★ 原文件没被写坏（内容与改前一致）")

# 再试一个"找不到原文"的情况
pre_approve("write", "hdl_edit %s: 测试" % RTL)
r3 = T.call("hw_hdl_edit", {
    "file": RTL, "old": "这段原文不存在xyz", "new": "x", "note": "测试",
}, {})
chk("找不到" in r3, "找不到原文时给出明确提示", r3[:60])

# 再试"不唯一"
pre_approve("write", "hdl_edit %s: 测试" % RTL)
r4 = T.call("hw_hdl_edit", {
    "file": RTL, "old": "    ", "new": "  ", "note": "测试",
}, {})
chk("不唯一" in r4, "匹配不唯一时拒绝", r4[:60])

# ══════════════════════════════════════════════════════════════ ③
print("\n【③】hw_fpga_build —— 提交构建任务（异步，不等）")
# ★ 先在权限层批准（模拟"用户点了同意"）
pre_approve("shell", "vivado build: 闭环测试：生成一个产物")
chk(True, "已模拟用户批准（policy 闸门是安全设计，不是 bug）")
r5 = T.call("hw_fpga_build", {
    "desc": "闭环测试：生成一个产物",
    "steps": [
        {"desc": "写一个假的 bitstream",
         "cmd": '"%s" -c "open(r\'%s\',\'wb\').write(b\'BIT\'*1000)"'
                % (sys.executable, os.path.join(TMP, "fake.bit"))},
    ],
    "artifacts": [os.path.join(TMP, "fake.bit")],
    "timeout_sec": 120,
    "wait": False,
}, {})
print("   " + r5.replace("\n", "\n   ")[:300])
chk("已提交" in r5, "任务提交成功")
reqs = [f for f in os.listdir(JOBS) if f.endswith(".request.json")]
chk(len(reqs) == 1, "任务文件写到了任务目录", str(reqs))
jid = reqs[0][:-len(".request.json")]
req = json.load(open(os.path.join(JOBS, reqs[0]), encoding="utf-8"))
chk(req.get("who") == "zynq-agent", "任务里有 who=zynq-agent")
chk(len(req.get("steps", [])) == 1, "步骤数正确")

# ══════════════════════════════════════════════════════════════ ④
print("\n【④】fpga_build_daemon —— 本地模式执行任务")
p = subprocess.run([sys.executable, os.path.join(HERE, "fpga_build_daemon.py"),
                    "--local", "--once"],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   timeout=300, cwd=HERE,
                   env={**os.environ, "FPGA_JOBS_DIR": JOBS})
out = p.stdout.decode("utf-8", "replace")
tail = "\n".join(out.strip().split("\n")[-12:])
print("   " + tail.replace("\n", "\n   "))
chk(p.returncode == 0, "守护退出码 0")

# 注意：守护用的是它自己的 JOBS_LOCAL；为了测试，我们把它指到同一个目录
res_path = os.path.join(JOBS, jid + ".result.json")

chk(os.path.exists(res_path), "守护写了结果文件")
if os.path.exists(res_path):
    res = json.load(open(res_path, encoding="utf-8"))
    chk(res.get("status") == "ok", "任务状态 = ok", str(res.get("status")))
    arts = res.get("artifacts", [])
    chk(arts and not arts[0].get("missing"), "产物被收集到",
        json.dumps(arts[0], ensure_ascii=False)[:90] if arts else "无")
    chk(arts and arts[0].get("md5"), "产物带 md5")

# ══════════════════════════════════════════════════════════════ ⑤
print("\n【⑤】hw_fpga_build_status —— 查结果")
r6 = T.call("hw_fpga_build_status", {"id": jid}, {})
print("   " + r6.replace("\n", "\n   ")[:300])
chk("ok" in r6, "能查到状态")
r7 = T.call("hw_fpga_build_status", {}, {})
chk(isinstance(r7, str) and ("任务" in r7 or "没有" in r7), "能列出任务")

# ══════════════════════════════════════════════════════════════ ⑥
print("\n【⑥】hw_verify —— 跑回归清单（板子不在，硬检查会失败，这是对的）")
r8 = T.call("hw_verify", {}, {})
first = r8.split("\n")[0] if r8 else ""
print("   " + r8.replace("\n", "\n   ")[:260])
chk(isinstance(r8, str), "返回字符串（没崩）")
chk("硬" in r8 or "检查" in r8, "看起来是回归清单的输出")

# ══════════════════════════════════════════════════════════════ ⑦
print("\n【⑦】hw_change_list —— 变更单都记下了吗")
r9 = T.call("hw_change_list", {"limit": 20}, {})
print("   " + r9.replace("\n", "\n   ")[:600])
chk("hdl" in r9, "记了 hdl 类型的变更")
chk("build" in r9, "记了 build 类型的变更")

# ══════════════════════════════════════════════════════════════ ⑧
print("\n【⑧】★ 回滚 —— 把 RTL 恢复回去")
recs = HC.change_list(50)
hdl_ids = [r["id"] for r in recs if r.get("kind") == "hdl"]
if hdl_ids:
    first_id = hdl_ids[0]
    pre_approve("write", "hw_change_rollback %s" % first_id)
    r10 = T.call("hw_change_rollback", {"id": first_id}, {})
    print("   " + r10.replace("\n", "\n   ")[:250])
    back = open(RTL, encoding="utf-8").read()

    chk("ext_valid" not in back, "★ RTL 回滚成功（ext_valid 没了）",
        "文件现在 %d 字节" % len(back))
else:
    chk(False, "没找到 hdl 变更单，无法测回滚")

print()
print("=" * 78)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 78)
print()
print("★ 这个闭环现在能做什么：")
print("   agent 改 RTL/BD → (PC 侧守护跑 Vivado) → 刷到板子 → 自动回归 → 不行回滚")
print("   每一步都有：备份、变更单、语法检查、自动验证")

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
