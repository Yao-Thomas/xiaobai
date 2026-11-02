#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rag_offline.py —— 验证接进 tiers.py 的本地 RAG（离线降级）

测三件事：
    ① 装载：RAG 有没有被认到（知识块数）
    ② mode=local：断网时能不能答项目领域问题（走 RAG，tier='rag'）
    ③ mode=auto 且云端通：会不会先用 RAG 检索再交给云端（grounded=True）

用法（板子上）:
    sudo python3 /home/zynq/test_rag_offline.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")


def main():
    from agent.tiers import Tiers

    print("=" * 76)
    print(" 本地 RAG 离线降级验证")
    print("=" * 76)

    # ── ① 装载 ──
    t = Tiers(mode="auto")
    d = t.describe()
    print()
    print("【1】装载")
    print("  mode          : %s" % d["mode"])
    print("  规则数         : %d" % d["rules"])
    print("  本地模型       : %s" % d["local_model"])
    print("  ★ 本地 RAG     : %s" % d["local_rag"])
    print("  RAG 可用       : %s" % d["rag_available"])
    print("  云端可达       : %s" % d["cloud_reachable"])

    # ── ② mode=local（模拟断网）──
    print()
    print("【2】mode=local（= 断网）时的回答")
    tl = Tiers(mode="local")
    qs = [
        "CNN 的量化公式是什么",
        "ES8388 的 DAC 音量寄存器是多少",
        "示波器的采样率是多少",
        "agent 改 FPGA 的流程是什么",
        "今天天气怎么样",                 # 应拒答
    ]
    for q in qs:
        r = tl.ask(q)
        print()
        print("  问: %s" % q)
        print("  层: %s   用时 %ss%s"
              % (r.get("tier"), r.get("elapsed"),
                 "   ★ 拒答" if r.get("refused") else ""))
        print("  答: %s" % str(r.get("reply", ""))[:200].replace("\n", " "))

    # ── ③ 规则层还是最快的 ──
    print()
    print("【3】规则层（确定性指令，不该走 RAG/模型）")
    for q in ("现在多少度", "磁盘还剩多少", "你叫什么"):
        r = tl.ask(q)
        print("  问: %-16s 层=%-6s 用时=%ss  → %s"
              % (q, r.get("tier"), r.get("elapsed"),
                 str(r.get("reply", ""))[:50].replace("\n", " ")))

    # ── ④ mode=auto + 假云端，看有没有 grounded 标记 ──
    print()
    print("【4】mode=auto + 假云端（验证 RAG 检索结果会塞进 prompt）")
    seen = {}

    def fake_cloud(prompt):
        seen["prompt"] = prompt
        return "（假云端回复）基于资料回答：..."

    ta = Tiers(mode="auto")
    r = ta.ask("CNN 的量化公式是什么", cloud_fn=fake_cloud)
    print("  层    : %s" % r.get("tier"))
    print("  grounded（用没用 RAG 检索）: %s" % r.get("grounded"))
    p = seen.get("prompt", "")
    print("  塞给云端的 prompt 长度: %d 字符" % len(p))
    if p:
        print("  prompt 前 300 字：")
        for ln in p[:300].split("\n"):
            print("    %s" % ln)

    print()
    print("=" * 76)
    ok = d["rag_available"]
    print(" 总体: %s" % ("★ RAG 已接进 Tier 1，离线可用"
                        if ok else "★ RAG 没装载成功"))
    print("=" * 76)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
