"""指标计算测试：手算校验（§10.1 验收项 #9）。"""
from __future__ import annotations

import unittest

from tidewatch.compute.momentum import classify_stage, returns_from_closes


class TestReturns(unittest.TestCase):
    def test_basic(self):
        closes = [100.0, 110.0, 121.0]
        r = returns_from_closes(closes, (1, 5, 20))
        self.assertAlmostEqual(r[1], 121.0 / 110.0 - 1.0, places=10)
        # 样本不足 -> None，不臆造 0
        self.assertIsNone(r[5])
        self.assertIsNone(r[20])

    def test_20d(self):
        # 21 个点，首=100，末=150
        closes = [100.0] * 20 + [150.0]
        r = returns_from_closes(closes, (1, 5, 20))
        self.assertAlmostEqual(r[20], 150.0 / 100.0 - 1.0, places=10)
        self.assertAlmostEqual(r[1], 150.0 / 100.0 - 1.0, places=10)

    def test_empty(self):
        r = returns_from_closes([], (1, 5, 20))
        self.assertIsNone(r[1])


class TestStage(unittest.TestCase):
    def test_four_quadrants(self):
        self.assertEqual(classify_stage(+0.1, +0.01), "持续领涨")
        self.assertEqual(classify_stage(+0.1, -0.01), "高位回落")
        self.assertEqual(classify_stage(-0.1, +0.01), "超跌反弹")
        self.assertEqual(classify_stage(-0.1, -0.01), "持续走弱")

    def test_missing(self):
        self.assertIsNone(classify_stage(None, 0.01))
        self.assertIsNone(classify_stage(0.01, None))


if __name__ == "__main__":
    unittest.main()
