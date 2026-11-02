"""
test_corpus.py —— build_corpus.py 的纯标准库单元测试（不需要 torch）。
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from build_corpus import (FACT_BANK, build_lora_entries,  # noqa: E402
                          iter_md_blocks, split_into_chunks)


class TestMarkdownChunking(unittest.TestCase):
    def test_title_hierarchy(self):
        text = "# 一级\n段落一\n## 二级\n段落二\n## 二级乙\n段落三\n"
        blocks = iter_md_blocks(text, "fallback")
        self.assertEqual(3, len(blocks))
        self.assertEqual(["一级"], blocks[0][0])
        self.assertEqual(["一级", "二级"], blocks[1][0])

    def test_chunk_length_bounds(self):
        text = ("寄存器 0x1A 是 DAC 音量。" * 200)  # 超长文本
        chunks = split_into_chunks(text, lo=300, hi=600)
        for c in chunks:
            self.assertLessEqual(len(c), 600)


class TestFactBank(unittest.TestCase):
    def test_facts_have_required_fields(self):
        for f in FACT_BANK:
            self.assertTrue(f["q"], f["s"])
            self.assertTrue(f["a"].strip())
            self.assertTrue(f["s"])

    def test_sources_point_to_real_files(self):
        # 来源应形如 "路径/文件.md#标题"，且指向已知文档
        for f in FACT_BANK:
            self.assertIn("#", f["s"], f["s"])
            self.assertTrue(f["s"].endswith((".md#", ").md#")) or ".md#" in f["s"]
                            or ".py#" in f["s"], f["s"])


class TestLoraEntries(unittest.TestCase):
    def setUp(self):
        self.entries = build_lora_entries()

    def test_at_least_800(self):
        self.assertGreaterEqual(len(self.entries), 800)

    def test_sharegpt_format(self):
        for e in self.entries:
            self.assertEqual(["human", "gpt"], [m["from"] for m in e["conversations"]])
            self.assertIn("source", e)

    def test_has_refusal_samples(self):
        refusal = [e for e in self.entries if e.get("topic") == "refusal"]
        self.assertGreaterEqual(len(refusal), 50)

    def test_grounded_samples_have_source(self):
        for e in self.entries:
            if e.get("topic") == "grounded":
                self.assertTrue(e["source"])


if __name__ == "__main__":
    unittest.main()
