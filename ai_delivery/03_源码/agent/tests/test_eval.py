"""
test_eval.py —— eval.py 的纯标准库单元测试（不需要 torch）。
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from eval import TEST_ITEMS, evaluate  # noqa: E402
from rag import REFUSAL_TEXT  # noqa: E402


class TestTestSet(unittest.TestCase):
    def test_at_least_40_items(self):
        self.assertGreaterEqual(len(TEST_ITEMS), 40)

    def test_at_least_8_refusal(self):
        n_ref = sum(1 for it in TEST_ITEMS if not it["answerable"])
        self.assertGreaterEqual(n_ref, 8)

    def test_answerable_items_have_keypoints_and_source(self):
        for it in TEST_ITEMS:
            if it["answerable"]:
                self.assertTrue(it["keypoints"], it["id"])
                self.assertTrue(it.get("source"), it["id"])


class TestEvaluate(unittest.TestCase):
    def test_metrics_with_stub(self):
        # 一个"完美回答"的 stub：可回答的问题返回含要点与来源的回答，拒答问题返回拒答话术
        def perfect(query):
            for it in TEST_ITEMS:
                if it["query"] == query:
                    if not it["answerable"]:
                        return REFUSAL_TEXT
                    kps = " ".join(it["keypoints"])
                    return f"答案是 {kps}（来源 {it['source']}）"
            return REFUSAL_TEXT

        res = evaluate(perfect)
        m = res["metrics"]
        self.assertAlmostEqual(m["keypoint_recall"], 1.0, places=6)
        self.assertAlmostEqual(m["refusal_accuracy"], 1.0, places=6)
        self.assertAlmostEqual(m["hallucination_rate"], 0.0, places=6)

    def test_hallucination_detected(self):
        # 对拒答问题也硬答 → 幻觉率应为 1.0
        def always_answer(query):
            return "我乱编一个答案"

        res = evaluate(always_answer)
        self.assertAlmostEqual(res["metrics"]["hallucination_rate"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
