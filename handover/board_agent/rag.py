"""
rag.py —— ★ 纯标准库实现的 RAG（检索增强生成）

设计约束（任务 D 明确要求）：
  · 只用 Python 标准库，不依赖 jieba / rank_bm25 / numpy / torch ——
    保证能在本地 Windows（无 torch）与板端（无第三方包）直接跑、被单测。
  · 中文友好检索：自实现 BM25 + 中文 bigram 分词（连续汉字切成相邻二元组），
    英文/数字/十六进制（如 0x43CC0000、MFQ、>>16）作为整词 token。
  · 拒答机制：检索最高分低于阈值时回答"这个问题不在我的知识范围内"，
    用于抑制幻觉（这是评测的一部分）。

用法：
    from rag import RAG, load_chunks
    rag = RAG(load_chunks("kb/chunks.jsonl"))
    print(rag.retrieve("ES8388 的 DAC 音量寄存器", k=3))
    print(rag.answer("CNN 量化公式是什么？"))
    print(rag.build_prompt("CNN 量化公式是什么？"))   # 有 LLM 时把检索结果塞进 prompt
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

# 让 Windows 控制台（默认 cp1252）也能正确打印中文
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 拒答时的统一话术（eval.py 通过 is_refusal 识别它）
REFUSAL_TEXT = "这个问题不在我的知识范围内，我无法给出可靠答案。"

# 判定"是否拒答"的关键词（命中其一即视为拒答）
_REFUSAL_MARKERS = ("不在我的知识范围", "不知道", "无法回答", "不清楚", "无可奉告")

# 检索分数阈值：best score <= 该值 → 拒答。
# 经校准：停用词过滤后，领域内问题 top 分数普遍 > 6.75，而闲聊式问题大多 <= 6；
# 6.0 能在"不误拒领域问题"的前提下拦掉大部分无关提问。可按需调高以更保守。
DEFAULT_SCORE_THRESHOLD = 6.0

# ---------------------------------------------------------------------------
# 分词：中文 bigram + 英文/数字整词
# ---------------------------------------------------------------------------
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[a-zA-Z0-9_]+(?:[./+-][a-zA-Z0-9_]+)*")  # 兼容 0x43CC0000、43CC、>>16、1GB


def tokenize(text: str) -> List[str]:
    """把文本切成检索 token：连续汉字→相邻二元组；字母/数字/十六进制→整词。"""
    if not text:
        return []
    text = text.lower()
    toks: List[str] = []
    # 先按拉丁词元切，其余交给 CJK 正则
    for m in _LATIN.finditer(text):
        toks.append(m.group())
    for m in _CJK.finditer(text):
        s = m.group()
        if len(s) == 1:
            toks.append(s)
        else:
            for i in range(len(s) - 1):
                toks.append(s[i:i + 2])
    return toks


# ---------------------------------------------------------------------------
# 停用词（查询侧）：过滤掉"怎么/什么/今天/我/是/的"等无信息量的功能词，
# 避免"今天天气怎么样"这类闲聊只靠"怎么"命中语料而得到假阳性高分。
# 只用于查询分词，不用于文档索引（文档侧保留全部 token 保证召回）。
# ---------------------------------------------------------------------------
STOPWORDS = frozenset(
    "的 了 是 吗 呢 啊 吧 呀 哦 谁 我 你 他 她 它 在 有 和 与 或 都 很 太 也 还 再 把 被 让 对 向 从 到 于 之 其 这 那 哪 几 个 条 种 些 点 元 万 亿 "
    "什么 怎么 怎样 如何 为何 为什么 哪个 哪些 多少 请问 帮我 帮忙 给我 一下 可以 应该 还是 或者 以及 就是 不是 没有 能够 想要 知道 了解 介绍 推荐 讲讲 说说 "
    "今天 明天 昨天 现在 最近 目前 时候 我们 你们 他们 这个 那个 这些 那些 一个 一些 有点 大概 关于 如果 因为 所以 但是 而且 并且 能否 需要 谢谢 你好 请问 "
    "么样 么做 么办 么是 么会 么能 么说 什么 怎么做 为什么 是什么".split()
)


# 查询同义扩展：把用户口语词映射到文档里的术语，缓解"主频 vs 时钟"这类词表错配。
# 只做"等价替换"不做事实推断，不改变检索的语义。
QUERY_SYNONYMS = {
    "主频": ["时钟", "mhz"],
    "内存": ["ddr", "ddr3"],
    "芯片": ["zynq", "xc7z020"],
    "采样率": ["msps"],
    "量化": ["mfq", "requant"],
    "录音": ["arecord"],
    "放音": ["aplay"],
    "采集": ["采样", "capture"],
}


def query_tokens(text: str) -> List[str]:
    """查询分词、去停用词、再做同义扩展。"""
    base = [t for t in tokenize(text) if t not in STOPWORDS]
    out = []
    for t in base:
        out.append(t)
        for s in QUERY_SYNONYMS.get(t, []):
            if s not in out:
                out.append(s)
    return out


# ---------------------------------------------------------------------------
# BM25（自实现）
# ---------------------------------------------------------------------------
class BM25:
    """经典 BM25：score = Σ idf(t) * tf*(k1+1) / (tf + k1*(1-b+b*dl/avgdl))"""

    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_tokens = [tokenize(d) for d in docs]
        self.N = len(self.doc_tokens)
        self.doc_len = [len(d) for d in self.doc_tokens]
        self.avgdl = sum(self.doc_len) / max(1, self.N)
        self.df = Counter()
        for d in self.doc_tokens:
            for t in set(d):
                self.df[t] += 1

    def _idf(self, t: str) -> float:
        n = self.df.get(t, 0)
        if n == 0:
            return 0.0
        return math.log(1.0 + (self.N - n + 0.5) / (n + 0.5))

    def score(self, query: str, idx: int) -> float:
        q = query_tokens(query)
        if not q:
            return 0.0
        d = self.doc_tokens[idx]
        tf = Counter(d)
        dl = self.doc_len[idx]
        s = 0.0
        for t in q:
            f = tf.get(t, 0)
            if f == 0:
                continue
            idf = self._idf(t)
            s += idf * f * (self.k1 + 1.0) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def top(self, query: str, k: int) -> List[Tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.N)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# chunk 载入 / 句子切分
# ---------------------------------------------------------------------------
def load_chunks(path: str) -> List[Dict]:
    """读取 kb/chunks.jsonl（每行一个 chunk JSON）。"""
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


_SENT_SPLIT = re.compile(r"[。！？；!?;]|\n")
_MD_NOISE = re.compile(r"\*\*|`|^\s*[#>*|-]+\s*")


def split_segments(text: str) -> List[str]:
    """把 chunk 文本切成"段"（按句末标点与换行），并清理 markdown 噪声。"""
    raw = _SENT_SPLIT.split(text)
    out = []
    for seg in raw:
        seg = seg.replace("**", "").replace("`", "").strip()
        seg = seg.strip("|").strip().strip("*- ").strip()
        if seg and seg not in ("|", "-"):
            out.append(seg)
    return out


def _seg_overlap(seg: str, q_tokens: set) -> int:
    return len(q_tokens.intersection(tokenize(seg)))


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------
class RAG:
    """纯标准库 RAG：BM25 检索 + 抽取式回答 + 拒答机制。"""

    def __init__(self, chunks: List[Dict], score_threshold: Optional[float] = None):
        if not chunks:
            raise ValueError("chunks 为空，无法构建索引（先运行 build_corpus.py）")
        self.chunks = chunks
        # 索引文本 = 标题路径（重复两遍，加权）+ 正文；标题命中优先级更高
        docs = []
        for c in chunks:
            title = " ".join(c.get("title_path", [])) if isinstance(c.get("title_path"), list) \
                else str(c.get("title_path", ""))
            docs.append(title + " " + title + " " + c.get("text", ""))
        self.bm25 = BM25(docs)
        self.score_threshold = DEFAULT_SCORE_THRESHOLD if score_threshold is None else score_threshold

    # ---- 检索 ----
    def retrieve(self, query: str, k: int = 3) -> List[Dict]:
        """返回 top-k 相关 chunks，带来源与 BM25 分数。"""
        out = []
        for idx, score in self.bm25.top(query, k):
            if score <= 0:
                break
            c = self.chunks[idx]
            out.append({
                "text": c.get("text", ""),
                "source": c.get("source", ""),
                "title_path": c.get("title_path", []),
                "id": c.get("id", idx),
                "score": score,
            })
        return out

    # ---- 抽取式回答（无 LLM） ----
    def answer(self, query: str, k: int = 3, max_chars: int = 300) -> str:
        """无 LLM 时的抽取式回答：拼最相关句子 + 列出处；低分时拒答。"""
        hits = self.retrieve(query, k)
        if not hits or hits[0]["score"] <= self.score_threshold:
            return REFUSAL_TEXT
        qtoks = set(query_tokens(query))
        # 每个命中 chunk 挑与 query 重叠最多的句子
        picked: List[str] = []
        sources: List[str] = []
        for h in hits:
            segs = split_segments(h["text"])
            if not segs:
                continue
            # 排序：重叠数降序，其次偏爱含数字/十六进制的"信息密集"段
            ranked = sorted(
                segs,
                key=lambda s: (_seg_overlap(s, qtoks), _has_num(s)),
                reverse=True,
            )
            for seg in ranked[:3]:
                if _seg_overlap(seg, qtoks) > 0:
                    picked.append(seg)
            src = self._source_label(h)
            if src and src not in sources:
                sources.append(src)
        if not picked:
            return REFUSAL_TEXT
        body = _join_budget(picked, max_chars)
        src_line = "；".join(sources[:3])
        return f"根据项目资料：{body}。\n来源：{src_line}"

    # ---- 有 LLM 时：把检索结果塞进 prompt ----
    def build_prompt(self, query: str, k: int = 3) -> str:
        """供云端大模型 / LoRA 小模型使用：把检索到的上下文拼进 prompt。"""
        hits = self.retrieve(query, k)
        if not hits or hits[0]["score"] <= self.score_threshold:
            return (
                "你是「系统管家小白」的本地助手。你只依据给定资料回答，资料里没有的就明确说不知道。\n"
                f"问题：{query}\n\n"
                "资料：（无相关条目）\n\n"
                "请回答：如果资料没有答案，请直接说“这个问题不在我的知识范围内”。"
            )
        ctx = "\n\n".join(
            f"[{i + 1}] {self._source_label(h)}\n{h['text']}" for i, h in enumerate(hits)
        )
        return (
            "你是「系统管家小白」的本地助手。你只依据下面给出的资料回答，不要编造资料里没有的内容；"
            "资料没有答案时请明确说“这个问题不在我的知识范围内”。\n\n"
            f"问题：{query}\n\n资料：\n{ctx}\n\n请用简洁的中文回答，并注明依据的条目编号。"
        )

    @staticmethod
    def _source_label(h: Dict) -> str:
        title = h.get("title_path", [])
        if isinstance(title, list) and title:
            tail = title[-1]
        elif isinstance(title, str) and title:
            tail = title
        else:
            tail = ""
        return f"{h.get('source', '')}#{tail}" if tail else str(h.get("source", ""))


def _has_num(seg: str) -> int:
    return 1 if re.search(r"[0-9]", seg) else 0


def _join_budget(segs: List[str], max_chars: int) -> str:
    """按预算拼接句子，尽量保留完整性。"""
    out = []
    used = 0
    for s in segs:
        if s in out:
            continue
        add = len(s) + 1
        if used + add > max_chars and out:
            break
        out.append(s)
        used += add
        if used >= max_chars:
            break
    return "。".join(out)


# ---------------------------------------------------------------------------
# 拒答判定（eval 与外部共用）
# ---------------------------------------------------------------------------
def is_refusal(text: str) -> bool:
    """判断一段回答是否属于"拒答"（用于评测拒答准确率与幻觉率）。"""
    if not text:
        return True
    return any(m in text for m in _REFUSAL_MARKERS)


if __name__ == "__main__":
    import sys
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    kb = os.path.join(_here, "kb", "chunks.jsonl")
    if not os.path.exists(kb):
        print("未找到 kb/chunks.jsonl，请先运行 build_corpus.py")
        sys.exit(1)
    rag = RAG(load_chunks(kb))
    for q in ["ES8388 的 DAC 音量寄存器是多少", "CNN 量化公式", "今天天气怎么样"]:
        print("Q:", q)
        print("A:", rag.answer(q))
        print("-" * 60)
