"""
test_rag.py —— rag.py 的纯标准库单元测试（不需要 torch）。
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from rag import (BM25, RAG, is_refusal, query_tokens, tokenize,  # noqa: E402
                 REFUSAL_TEXT, split_segments)


class TestTokenize(unittest.TestCase):
    def test_cjk_bigram(self):
        toks = tokenize("音频寄存器")
        self.assertIn("音频", toks)
        self.assertIn("寄存", toks)

    def test_latin_token(self):
        self.assertIn("es8388", tokenize("ES8388 的寄存器"))
        self.assertIn("0x43cc0000", tokenize("地址 0x43CC0000"))

    def test_single_cjk_char(self):
        self.assertEqual(["点"], tokenize("点"))

    def test_query_tokens_filters_stopwords(self):
        # "怎么" 是停用词，应被过滤；"寄存器" 保留
        self.assertIn("寄存", query_tokens("寄存器怎么读"))

    def test_synonym_expansion(self):
        self.assertIn("mfq", query_tokens("量化公式"))


class TestBM25(unittest.TestCase):
    def test_basic_scoring(self):
        bm = BM25(["FPGA 量化 MFQ 寄存器", "今天天气很好", "音频 ES8388 寄存器"])
        self.assertGreater(bm.score("MFQ 寄存器", 0), 0.0)
        self.assertGreater(bm.score("ES8388", 2), 0.0)
        # 不相关文档得分应低于相关文档
        self.assertLess(bm.score("MFQ 寄存器", 1), bm.score("MFQ 寄存器", 0))


class TestSplitSegments(unittest.TestCase):
    def test_cleans_markdown(self):
        segs = split_segments("| 0x1A | DAC 音量 | **0x00** |")
        self.assertTrue(any("0x00" in s for s in segs))
        self.assertTrue(all("**" not in s for s in segs))


class TestRAG(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            {"id": "c0", "source": "doc/audio.md", "title_path": ["音频", "ES8388"],
             "text": "ES8388 的 DAC 音量寄存器是 0x1A，写 0x00 表示 0 dB。"},
            {"id": "c1", "source": "doc/cnn.md", "title_path": ["CNN", "量化"],
             "text": "CNN 量化公式 out = relu/sat((acc × MFQ) >> 16)，MFQ 是寄存器。"},
        ]
        self.rag = RAG(self.chunks, score_threshold=0.0)

    def test_retrieve_returns_source(self):
        hits = self.rag.retrieve("ES8388 DAC 音量", k=1)
        self.assertEqual(1, len(hits))
        self.assertEqual("doc/audio.md", hits[0]["source"])

    def test_answer_includes_keypoint(self):
        ans = self.rag.answer("ES8388 的 DAC 音量寄存器是多少")
        self.assertIn("0x1A", ans)
        self.assertIn("doc/audio.md", ans)

    def test_refusal_on_out_of_domain(self):
        ans = self.rag.answer("今天天气怎么样")
        self.assertEqual(REFUSAL_TEXT, ans)
        self.assertTrue(is_refusal(ans))

    def test_build_prompt_includes_context(self):
        p = self.rag.build_prompt("ES8388 寄存器")
        self.assertIn("doc/audio.md", p)


class TestIsRefusal(unittest.TestCase):
    def test_refusal_markers(self):
        self.assertTrue(is_refusal("这个问题不在我的知识范围内"))
        self.assertTrue(is_refusal("我不知道"))
        self.assertFalse(is_refusal("ES8388 寄存器是 0x1A"))


if __name__ == "__main__":
    unittest.main()
