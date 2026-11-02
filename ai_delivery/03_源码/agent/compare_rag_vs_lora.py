"""
compare_rag_vs_lora.py —— ★ 任务书要求的那份"诚实对比"

用同一份内置测试集（eval.TEST_ITEMS）同时评测：
  ① RAG（纯标准库抽取式，无 LLM）
  ② LoRA（微调后的 Qwen2.5-0.5B，需 torch/transformers，服务器上跑）
  ③ RAG + LoRA（把检索上下文塞进 prompt 再让 LoRA 生成）

输出：一张对比表（markdown + json）。★ 不许美化结论 —— LoRA 不如 RAG 就照实写。

用法：
    # 只评 RAG（本地、无 torch 也能跑）
    python compare_rag_vs_lora.py --kb kb/chunks.jsonl --out compare_report

    # 服务器上：加上 LoRA 两条路线
    python compare_rag_vs_lora.py --kb kb/chunks.jsonl \
        --lora-model lora_model/merged --out compare_report
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eval import TEST_ITEMS, evaluate  # noqa: E402
from rag import RAG, load_chunks  # noqa: E402


def _build_lora_answer_fn(model_path: str):
    """惰性 import transformers，构造 LoRA 生成函数（服务器上才需要）。"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True)
    model.eval()

    def fn(query, context_prompt=None):
        if context_prompt is not None:
            prompt = context_prompt
        else:
            prompt = ("你是「系统管家小白」。只依据资料回答，资料没有就明确说"
                      "“这个问题不在我的知识范围内”。\n问题：" + query)
        ids = tok(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=96, do_sample=False,
                                 temperature=None, top_p=None)
        return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    return fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=os.path.join(_HERE, "kb", "chunks.jsonl"))
    ap.add_argument("--lora-model", default=None)
    ap.add_argument("--out", default=os.path.join(_HERE, "compare_report"))
    args = ap.parse_args()

    if not os.path.exists(args.kb):
        print("未找到 kb/chunks.jsonl，请先运行 build_corpus.py")
        return 1
    rag = RAG(load_chunks(args.kb))

    results = {}

    # ① RAG
    results["rag"] = evaluate(rag.answer)["metrics"]

    # ②③ LoRA / RAG+LoRA
    if args.lora_model:
        try:
            lora_fn = _build_lora_answer_fn(args.lora_model)
            results["lora"] = evaluate(lora_fn)["metrics"]
            results["rag_plus_lora"] = evaluate(
                lambda q: lora_fn(q, context_prompt=rag.build_prompt(q)))["metrics"]
        except ImportError:
            print("未安装 torch/transformers，跳过 LoRA 两条路线（本机为纯标准库环境）")
        except Exception as e:  # noqa: BLE001
            print(f"LoRA 评测失败（{e}），跳过 LoRA 两条路线")
    else:
        print("未提供 --lora-model，只评 RAG（LoRA 两条路线需在服务器上跑）")

    # ---- 输出对比表 ----
    metrics_order = [
        ("keypoint_recall", "要点命中率"),
        ("source_hit_rate", "来源命中率"),
        ("refusal_accuracy", "拒答准确率"),
        ("hallucination_rate", "幻觉率"),
    ]
    names = {"rag": "RAG", "lora": "LoRA", "rag_plus_lora": "RAG+LoRA"}

    md = ["# RAG vs LoRA 对比（同一份测试集）", ""]
    md.append("| 路线 | " + " | ".join(cn for _, cn in metrics_order) + " |")
    md.append("|---|---|---|---|---|")
    for key in ("rag", "lora", "rag_plus_lora"):
        if key not in results:
            continue
        m = results[key]
        md.append("| " + names[key] + " | " + " | ".join(
            f"{m[k]:.3f}" for k, _ in metrics_order) + " |")
    md.append("")
    md.append("## 诚实结论")
    md.append("")
    md.append("> 竞赛项目几百~几千条对话微调出的 LoRA 小模型，效果大概率不如"
              "「大模型 + RAG」。本表不美化：哪条路线分数高就照实写。")
    md.append("")
    if "rag" in results and "lora" in results:
        r, l = results["rag"], results["lora"]
        if r["keypoint_recall"] >= l["keypoint_recall"]:
            md.append(f"本实验里 RAG 要点命中率 {r['keypoint_recall']:.3f} "
                      f"vs LoRA {l['keypoint_recall']:.3f} —— RAG 不输 LoRA，"
                      "符合任务书的诚实提醒。")
        else:
            md.append(f"本实验里 LoRA 要点命中率 {l['keypoint_recall']:.3f} "
                      f"高于 RAG {r['keypoint_recall']:.3f}。")

    report = "\n".join(md)
    print(report)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "compare.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(report + "\n")
    with open(os.path.join(args.out, "compare.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n已写出：{os.path.join(args.out, 'compare.md')} / {os.path.join(args.out, 'compare.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
