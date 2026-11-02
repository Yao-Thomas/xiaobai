#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_rollback.py —— 单独调试"改了再回滚"，看文件到底恢复没有"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TMP = tempfile.mkdtemp(prefix="dbgroll_")
JOBS = os.path.join(TMP, "jobs")
os.makedirs(JOBS, exist_ok=True)
os.environ["FPGA_JOBS_DIR"] = JOBS
os.environ["HWCHANGE_DIR"] = os.path.join(TMP, "hc")

from agent import tools as T                                     # noqa: E402
from agent import policy as POL                                  # noqa: E402
import agent.hw_change as HC                                     # noqa: E402
import agent.hw_tools as HW                                      # noqa: E402

HC.CHANGE_DIR = os.environ["HWCHANGE_DIR"]
HC.CHANGE_FILE = os.path.join(HC.CHANGE_DIR, "changes.jsonl")
HC.SNAPSHOT_DIR = os.path.join(HC.CHANGE_DIR, "snapshots")
HW.CHANGE_DIR = HC.CHANGE_DIR
HW.CHANGE_FILE = HC.CHANGE_FILE


def approve(kind, payload):
    rid = POL.request(kind, payload, "调试")
    POL.resolve(rid, True)


RTL = os.path.join(TMP, "t.v")
ORIG = """// 测试文件
module t (
    input wire clk
);
    reg [7:0] cnt;
    always @(posedge clk) begin
        cnt <= cnt + 8'd1;
    end
endmodule
"""
open(RTL, "w", encoding="utf-8").write(ORIG)
print("原始文件 %d 字节" % len(ORIG))
print("  含 ext_valid: %s" % ("ext_valid" in ORIG))
print()

# ---- 改 ----
approve("write", "hdl_edit %s: 加端口" % RTL)
r = T.call("hw_hdl_edit", {
    "file": RTL,
    "old": "    input wire clk\n);",
    "new": "    input wire clk,\n    input wire ext_valid\n);",
    "note": "加 ext_valid 端口",
}, {})
print("改动结果:")
print("  " + r.replace("\n", "\n  ")[:400])
after = open(RTL, encoding="utf-8").read()
print()
print("改后文件 %d 字节，含 ext_valid: %s" % (len(after), "ext_valid" in after))
print()

# ---- 看变更单 ----
recs = HC.change_list(10)
print("变更单 (%d 条):" % len(recs))
for x in recs:
    print("  id=%s kind=%s 有backup=%s backup=%s"
          % (x.get("id"), x.get("kind"), bool(x.get("backup")),
             (x.get("backup") or "")[-40:]))
print()

hdl = [x for x in recs if x.get("kind") == "hdl"]
if not hdl:
    print("★ 没有 hdl 变更单，退不出")
    sys.exit(1)

cid = hdl[0]["id"]
print("用 id=%s 回滚" % cid)
ok, why = HC.rollback(cid, verbose=True)
print("  返回: ok=%s why=%s" % (ok, why))
print()

back = open(RTL, encoding="utf-8").read()
print("回滚后文件 %d 字节，含 ext_valid: %s" % (len(back), "ext_valid" in back))
print("  和原文一致: %s" % (back == ORIG))
if back != ORIG:
    print()
    print("  --- 回滚后的内容 ---")
    for ln in back.split("\n"):
        print("    " + ln)
    print("  --- 原文 ---")
    for ln in ORIG.split("\n"):
        print("    " + ln)
