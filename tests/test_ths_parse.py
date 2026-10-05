"""同花顺解析测试：验证 fixture 能被正确解析。"""
from __future__ import annotations

import unittest

from tidewatch.datasource.ths import ThsSource
from tests.helpers import FakeHttp


class TestThsParse(unittest.TestCase):
    def test_list_industry(self):
        http = FakeHttp({"thshy/": "ths/list_industry.html"})
        src = ThsSource(http)
        sectors = src.list_sectors("industry")
        # HTML 里 140 个链接，去重后 90 个唯一行业代码
        self.assertEqual(len(sectors), 90)
        self.assertEqual(sectors[0].category, "industry")
        self.assertEqual(sectors[0].provider, "ths")
        self.assertTrue(all(s.sector_code.startswith("88") for s in sectors))
        # 去重生效
        self.assertEqual(len({s.sector_code for s in sectors}), 90)

    def test_list_concept(self):
        # 概念板块从列表页内嵌 gnSection JSON 解析：293 个，代码 885xxx/886xxx
        http = FakeHttp({"gn/": "ths/list_concept.html"})
        sectors = ThsSource(http).list_sectors("concept")
        self.assertEqual(len(sectors), 293)
        self.assertEqual(sectors[0].category, "concept")
        self.assertTrue(all(s.sector_code.startswith("88") for s in sectors))
        self.assertTrue(all(s.name for s in sectors), "every concept must carry a name")
        # 去重
        self.assertEqual(len({s.sector_code for s in sectors}), 293)

    def test_fetch_sector_kline(self):
        http = FakeHttp({"bk_881101": "ths/kline_881101.js"})
        name, klines = ThsSource(http).fetch_sector("881101")
        self.assertEqual(name, "种植业与林业")
        self.assertEqual(len(klines), 140)
        # 升序
        dates = [k.date for k in klines]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(klines[-1].date, "20260930")
        self.assertGreater(klines[-1].close, 0)
        self.assertGreater(klines[-1].amount, 0)


if __name__ == "__main__":
    unittest.main()
