"""
eval.py —— ★ 纯标准库评测（任务 D 验收）

内置一份领域问答测试集（≥40 条，含 ≥8 条"应该拒答"），并实现四个指标：
  · 要点命中率 keypoint_recall —— 正确答案要点出现在模型回答里的比例
  · 来源命中率 source_hit_rate —— 回答是否带出正确来源文件（主要对 RAG 有意义）
  · 拒答准确率 refusal_accuracy —— 该拒答时拒答、该回答时回答的正确率
  · 幻觉率 hallucination_rate —— 本应拒答却被回答了（编造）的比例

支持评测任意 answer(query)->str 的 callable，所以既能评 RAG，也能评 LoRA 模型。

用法：
    python eval.py                        # 用 kb/chunks.jsonl 构建 RAG 并评测
    python eval.py --answer-jsonl xx.jsonl  # 评测外部生成的回答（LoRA 等）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable, Dict, List, Optional

# 让 Windows 控制台（默认 cp1252）也能正确打印中文
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rag import RAG, load_chunks, is_refusal  # noqa: E402

# ---------------------------------------------------------------------------
# ★ 内置测试集（领域问答 + 正确答案要点 + 来源）
#   keypoints 是"要点关键词/短语"，只要出现在回答里就算命中（大小写不敏感）。
# ---------------------------------------------------------------------------
TEST_ITEMS: List[Dict] = [
    # ---- 项目整体 / 硬件规格 ----
    {"id": "q01", "query": "系统管家小白是什么项目", "answerable": True,
     "keypoints": ["Zynq-7020", "嵌入式小电脑"],
     "source": "AI训练交接包(1)/04_项目背景/项目总览.md#一、项目目标"},
    {"id": "q02", "query": "板子用的什么主控芯片", "answerable": True,
     "keypoints": ["XC7Z020", "Cortex-A9"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"id": "q03", "query": "板子有多少内存", "answerable": True,
     "keypoints": ["1 GB", "DDR3"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#一、开发板"},
    {"id": "q04", "query": "ARM 处理器主频是多少", "answerable": True,
     "keypoints": ["666.666666", "Cortex-A9"],
     "source": "work/prev_cnn/设计文档/BOARD_CONFIG.md#1. PS"},
    {"id": "q05", "query": "自研 GPU 的寄存器地址是多少", "answerable": True,
     "keypoints": ["0x43CB0000"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表"},
    {"id": "q06", "query": "示波器的寄存器地址是多少", "answerable": True,
     "keypoints": ["0x43CC0000"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表"},
    {"id": "q07", "query": "CNN 加速器预留的地址是什么", "answerable": True,
     "keypoints": ["0x43CD0000", "0x43CE0000"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表"},
    {"id": "q08", "query": "i2c2 总线的地址是多少", "answerable": True,
     "keypoints": ["0x41600000"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#五、地址分配总表"},
    # ---- SSH / 刷写 ----
    {"id": "q09", "query": "怎么通过 SSH 连接开发板", "answerable": True,
     "keypoints": ["zynq@192.168.10.23", "123456"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#SSH"},
    {"id": "q10", "query": "怎么安全地刷写 bitstream", "answerable": True,
     "keypoints": ["md5", "mv"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#红线 5"},
    {"id": "q11", "query": "bitstream 文件在板子的哪个路径", "answerable": True,
     "keypoints": ["/mnt/boot/system.bit"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#八、板子上的重要文件"},
    # ---- ES8388 ----
    {"id": "q12", "query": "ES8388 的 DAC 音量寄存器是多少", "answerable": True,
     "keypoints": ["0x1A", "0x00"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q13", "query": "ES8388 怎么提高输出摆幅", "answerable": True,
     "keypoints": ["0x1D", "4.0V"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q14", "query": "ES8388 怎么让 DAC 输出到功放", "answerable": True,
     "keypoints": ["0x27", "0xF8"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q15", "query": "ES8388 耳机座音量怎么调", "answerable": True,
     "keypoints": ["0x2E", "33"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q16", "query": "ES8388 录音时 ADC 电源寄存器写多少", "answerable": True,
     "keypoints": ["0x03", "0x51"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q17", "query": "ES8388 麦克风输入选择寄存器", "answerable": True,
     "keypoints": ["0x0A", "0x00"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#关键寄存器"},
    {"id": "q18", "query": "在板子上录音用什么命令", "answerable": True,
     "keypoints": ["arecord", "S24_LE"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#常用命令"},
    {"id": "q19", "query": "喇叭放音之前是什么问题", "answerable": True,
     "keypoints": ["BCLK", "跨时钟域"],
     "source": "AI训练交接包(1)/01_任务书/01_功能清单.md#二、音频链路"},
    # ---- 示波器 IP ----
    {"id": "q20", "query": "示波器 IP 叫什么名字", "answerable": True,
     "keypoints": ["scope_cap_axi", "0x43CC0000"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"id": "q21", "query": "示波器一次采集多少点", "answerable": True,
     "keypoints": ["4096", "双 bank"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"id": "q22", "query": "示波器的采样率是多少", "answerable": True,
     "keypoints": ["20 MSPS", "DIV"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"id": "q23", "query": "示波器的时基范围是多少", "answerable": True,
     "keypoints": ["50 ns", "12.7"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#五、示波器 IP"},
    {"id": "q24", "query": "示波器 DDS 频率怎么计算", "answerable": True,
     "keypoints": ["FREQ", "20MHz"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"id": "q25", "query": "怎么确认示波器 IP 在线", "answerable": True,
     "keypoints": ["0x53434F50", "SCOP"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#寄存器（偏移）"},
    {"id": "q26", "query": "capture_once 返回什么字段", "answerable": True,
     "keypoints": ["4096", "trig_pos"],
     "source": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ③"},
    {"id": "q27", "query": "set_dds 的波形参数怎么编码", "answerable": True,
     "keypoints": ["0=正弦", "3=锯齿"],
     "source": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ③"},
    # ---- CNN 量化 ----
    {"id": "q28", "query": "CNN 加速器的量化公式是什么", "answerable": True,
     "keypoints": ["MFQ", ">>16"],
     "source": "AI训练交接包(1)/00_README_先读我.md#★ 量化必须沿用上一轮的方案"},
    {"id": "q29", "query": "MFQ=119 是什么意思", "answerable": True,
     "keypoints": ["MFQ=119", "寄存器"],
     "source": "ai_training/docs/00_接口冻结单.md#4.2 依据"},
    {"id": "q30", "query": "CNN 的网络结构是怎样的", "answerable": True,
     "keypoints": ["28×28", "400"],
     "source": "ai_training/docs/00_接口冻结单.md#1. ★★ 最关键的一条"},
    {"id": "q31", "query": "为什么输入锁定 28×28 而不是 32×32", "answerable": True,
     "keypoints": ["400", "576"],
     "source": "ai_training/docs/00_接口冻结单.md#1. ★★ 最关键的一条"},
    {"id": "q32", "query": "CNN 权重的内存布局是什么", "answerable": True,
     "keypoints": ["KH*KW", "oc*IN"],
     "source": "ai_training/src/common/qmodel.py#硬件事实"},
    {"id": "q33", "query": "CNN 量化溢出的约束是什么", "answerable": True,
     "keypoints": ["2^31"],
     "source": "ai_training/docs/00_接口冻结单.md#4.4 溢出"},
    {"id": "q34", "query": "MFQ 的值该怎么标定", "answerable": True,
     "keypoints": ["65536", "max|acc|"],
     "source": "ai_training/docs/00_接口冻结单.md#4.3 为什么新模型不能直接用 119"},
    {"id": "q35", "query": "非真实 requantization 是什么坑", "answerable": True,
     "keypoints": [">>8", "argmax"],
     "source": "AI训练交接包(1)/00_README_先读我.md#五、上一轮的经验"},
    {"id": "q36", "query": "CNN 输入量化怎么定义", "answerable": True,
     "keypoints": ["u8 - 128", "int8"],
     "source": "ai_training/docs/00_接口冻结单.md#3. ★ 输入量化"},
    {"id": "q37", "query": "波形识别一共有几类", "answerable": True,
     "keypoints": ["9 类", "duty_abnormal"],
     "source": "ai_training/docs/00_接口冻结单.md#★ 类别表"},
    # ---- 接口 ----
    {"id": "q38", "query": "模型交付格式包含哪些文件", "answerable": True,
     "keypoints": ["weights.bin", "model_spec.json", "reference_out.bin"],
     "source": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ①"},
    {"id": "q39", "query": "为什么必须提供 reference_out.bin", "answerable": True,
     "keypoints": ["逐点", "一致"],
     "source": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#为什么必须要"},
    {"id": "q40", "query": "云端推理 API 的请求格式是什么", "answerable": True,
     "keypoints": ["/infer", "confidence"],
     "source": "AI训练交接包(1)/02_接口与规则/07_接口约定单.md#接口 ④"},
    {"id": "q41", "query": "STFT 时频图用什么参数", "answerable": True,
     "keypoints": ["NFFT=512", "HOP=132"],
     "source": "ai_training/docs/00_接口冻结单.md#2. ★ 输入形态"},
    {"id": "q42", "query": "分级推理如何降级到离线模式", "answerable": True,
     "keypoints": ["0.7", "离线模式"],
     "source": "ai_training/docs/00_接口冻结单.md#6. 接口 ④"},
    # ---- 坑 ----
    {"id": "q43", "query": "XADC 输入超压有什么危险", "answerable": True,
     "keypoints": ["1V", "打坏"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    {"id": "q44", "query": "CNN 结果尾部全 0 是什么原因", "answerable": True,
     "keypoints": ["cache line", "Xil_DCache"],
     "source": "AI训练交接包(1)/00_README_先读我.md#五、上一轮的经验"},
    {"id": "q45", "query": "HLS 打包的 core_revision 是什么坑", "answerable": True,
     "keypoints": ["core_revision", "ipx::package_project"],
     "source": "AI训练交接包(1)/04_项目背景/项目总览.md#⏳ 唯一剩余"},
    {"id": "q46", "query": "Verilog 不写位宽会怎样", "answerable": True,
     "keypoints": ["1 位", "截断"],
     "source": "AI训练交接包(1)/02_接口与规则/09_板子与工具链.md#七、★ 已知的坑"},
    # ---- 协作 / 其它 ----
    {"id": "q47", "query": "项目的协作红线有哪些", "answerable": True,
     "keypoints": ["BD 修改权", "reference_out.bin"],
     "source": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#④ 协作红线"},
    {"id": "q48", "query": "多个 agent 并行要注意什么", "answerable": True,
     "keypoints": ["任务独立", "同一时刻"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#三、多 agent 并发规则"},
    {"id": "q49", "query": "出流后的回归清单测什么", "answerable": True,
     "keypoints": ["桌面能起", "示波器能采"],
     "source": "AI训练交接包(1)/02_接口与规则/08_协作规则.md#六、回归清单"},
    {"id": "q50", "query": "示波器自动设置为什么适合用 RL", "answerable": True,
     "keypoints": ["序列决策", "4.3 ms"],
     "source": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 E"},
    {"id": "q51", "query": "agent 的硬件工具集有哪些", "answerable": True,
     "keypoints": ["_hdl_edit", "_flash_bitstream"],
     "source": "AI训练交接包(1)/01_任务书/06_分工总表_核对版.md#3. Agent 硬件工具集"},
    {"id": "q52", "query": "本地 agent 模型用什么基座微调", "answerable": True,
     "keypoints": ["Qwen", "0.5B", "LoRA"],
     "source": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 D"},
    {"id": "q53", "query": "板子 1GB 内存能跑本地大模型吗", "answerable": True,
     "keypoints": ["1 GB", "350 MB"],
     "source": "AI训练交接包(1)/01_任务书/04_分工_AI训练负责人.md#任务 D"},

    # ---- 应该拒答的样本（≥8 条） ----
    {"id": "r01", "query": "今天天气怎么样", "answerable": False, "keypoints": [], "source": None},
    {"id": "r02", "query": "明天上海会下雨吗", "answerable": False, "keypoints": [], "source": None},
    {"id": "r03", "query": "推荐一只今天值得买的股票", "answerable": False, "keypoints": [], "source": None},
    {"id": "r04", "query": "西红柿炒鸡蛋怎么做", "answerable": False, "keypoints": [], "source": None},
    {"id": "r05", "query": "最近有什么好看的电影推荐", "answerable": False, "keypoints": [], "source": None},
    {"id": "r06", "query": "世界杯的冠军是谁", "answerable": False, "keypoints": [], "source": None},
    {"id": "r07", "query": "给我讲个笑话", "answerable": False, "keypoints": [], "source": None},
    {"id": "r08", "query": "圆周率第 100 位是多少", "answerable": False, "keypoints": [], "source": None},
    {"id": "r09", "query": "帮我算一下今天的运势", "answerable": False, "keypoints": [], "source": None},
    {"id": "r10", "query": "怎么才能考上清华", "answerable": False, "keypoints": [], "source": None},
    {"id": "r11", "query": "特朗普最近说了什么", "answerable": False, "keypoints": [], "source": None},
    {"id": "r12", "query": "我的手机坏了怎么修", "answerable": False, "keypoints": [], "source": None},
]


def _basename(source: Optional[str]) -> str:
    if not source:
        return ""
    f = source.split("#")[0]
    base = os.path.basename(f)
    return base.replace(".md", "").replace(".py", "").lower()


def _contains(text: str, kw: str) -> bool:
    return kw.lower() in (text or "").lower()


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def evaluate(answer_fn: Callable[[str], str],
             items: Optional[List[Dict]] = None) -> Dict:
    """对任意 answer(query)->str 评测，返回指标 dict 与逐条结果。"""
    items = items if items is not None else TEST_ITEMS
    per_item = []
    ans_items = [it for it in items if it["answerable"]]
    ref_items = [it for it in items if not it["answerable"]]

    # 要点命中率
    kp_total = kp_hit = 0
    src_hit = 0
    for it in ans_items:
        ans = answer_fn(it["query"])
        hits = sum(1 for k in it["keypoints"] if _contains(ans, k))
        kp_hit += hits
        kp_total += len(it["keypoints"])
        if it.get("source") and _contains(ans, _basename(it["source"])):
            src_hit += 1
        per_item.append({
            "id": it["id"], "query": it["query"], "answerable": True,
            "refused": is_refusal(ans),
            "keypoints_hit": hits, "keypoints_total": len(it["keypoints"]),
            "source_hit": bool(it.get("source") and _contains(ans, _basename(it["source"]))),
        })

    # 拒答准确率 + 幻觉率
    refusal_correct = 0
    hallucinated = 0
    for it in ref_items:
        ans = answer_fn(it["query"])
        refused = is_refusal(ans)
        if refused:
            refusal_correct += 1
        else:
            hallucinated += 1
        per_item.append({
            "id": it["id"], "query": it["query"], "answerable": False,
            "refused": refused, "keypoints_hit": 0, "keypoints_total": 0,
            "source_hit": False,
        })

    n_ans = len(ans_items)
    n_ref = len(ref_items)
    # 拒答准确率 = (该拒答且拒答 + 该回答且没拒答) / 总数
    answered_correct = sum(1 for p in per_item if p["answerable"] and not p["refused"])
    refusal_accuracy = (refusal_correct + answered_correct) / max(1, len(items))

    metrics = {
        "n_items": len(items),
        "n_answerable": n_ans,
        "n_refusal": n_ref,
        "keypoint_recall": (kp_hit / kp_total) if kp_total else 0.0,
        "source_hit_rate": (src_hit / n_ans) if n_ans else 0.0,
        "refusal_accuracy": refusal_accuracy,
        "hallucination_rate": (hallucinated / n_ref) if n_ref else 0.0,
    }
    return {"metrics": metrics, "per_item": per_item}


def format_report(metrics: Dict, per_item: List[Dict]) -> str:
    m = metrics
    lines = []
    lines.append("# 领域问答评测报告")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 样本总数 | {m['n_items']}（可回答 {m['n_answerable']} / 应拒答 {m['n_refusal']}） |")
    lines.append(f"| 要点命中率 keypoint_recall | {m['keypoint_recall']:.3f} |")
    lines.append(f"| 来源命中率 source_hit_rate | {m['source_hit_rate']:.3f} |")
    lines.append(f"| 拒答准确率 refusal_accuracy | {m['refusal_accuracy']:.3f} |")
    lines.append(f"| 幻觉率 hallucination_rate | {m['hallucination_rate']:.3f} |")
    lines.append("")
    lines.append("## 逐条结果")
    lines.append("")
    lines.append("| id | 是否拒答 | 可回答 | 要点命中 | 来源命中 | 问题 |")
    lines.append("|---|---|---|---|---|---|")
    for p in per_item:
        kp = f"{p['keypoints_hit']}/{p['keypoints_total']}"
        lines.append(
            f"| {p['id']} | {'是' if p['refused'] else '否'} | "
            f"{'是' if p['answerable'] else '否'} | {kp} | "
            f"{'是' if p['source_hit'] else '否'} | {p['query']} |")
    return "\n".join(lines)


def _load_answer_fn(answer_jsonl: str) -> Callable[[str], str]:
    """从 {query, answer} 的 jsonl 构造 answer_fn（用于评测 LoRA 等外部回答）。"""
    mapping: Dict[str, str] = {}
    with open(answer_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            mapping[o["query"]] = o.get("answer", "")
    return lambda q: mapping.get(q, "")


def main() -> int:
    ap = argparse.ArgumentParser(description="评测 RAG（或外部回答）")
    ap.add_argument("--kb", default=os.path.join(_HERE, "kb", "chunks.jsonl"))
    ap.add_argument("--answer-jsonl", default=None, help="外部回答文件（评测 LoRA 用）")
    ap.add_argument("--out", default=os.path.join(_HERE, "eval_report.json"))
    ap.add_argument("--out-md", default=os.path.join(_HERE, "eval_report.md"))
    args = ap.parse_args()

    if args.answer_jsonl:
        fn = _load_answer_fn(args.answer_jsonl)
        name = "外部回答（LoRA）"
    else:
        if not os.path.exists(args.kb):
            print("未找到 kb/chunks.jsonl，请先运行 build_corpus.py")
            return 1
        rag = RAG(load_chunks(args.kb))
        fn = rag.answer
        name = "RAG"

    result = evaluate(fn)
    md = format_report(result["metrics"], result["per_item"])
    print(f"### 评测对象：{name}")
    print(md)

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(args.out_md, "w", encoding="utf-8", newline="\n") as f:
        f.write(md + "\n")
    print(f"\n已写出：{args.out} / {args.out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
