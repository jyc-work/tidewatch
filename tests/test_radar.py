"""资金雷达测试（离线，FakeHttp 造 push2ex 响应）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tidewatch.pipeline.radar import run_radar
from tidewatch.render.builder import SiteBuilder
from tidewatch.store.db import Store
from tests.helpers import FakeFetched

TRADE_DATE = "2026-09-30"


class _PoolFakeHttp:
    """按 endpoint 返回对应池数据。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_with_fallback(self, hosts, path, *, params=None, headers=None):
        self.calls.append(path)
        if "getTopicZTPool" in path:
            tc, pool = 2, [
                {"c": "603127", "n": "昭衍新药", "p": 20200, "zdp": 10.0, "amount": 2647000000,
                 "ltsz": 1e10, "hs": 8.83, "lbc": 1, "fund": 1e8, "zbc": 0, "hybk": "医疗服务"},
                {"c": "000678", "n": "襄阳轴承", "p": 1075, "zdp": 9.98, "amount": 1075000000,
                 "ltsz": 1e10, "hs": 19.65, "lbc": 4, "fund": 5e7, "zbc": 0, "hybk": "汽车零部件"},
            ]
        elif "getTopicZBPool" in path:
            tc, pool = 1, [
                {"c": "002262", "n": "恩华药业", "p": 22730, "zdp": 5.72, "amount": 670320320,
                 "ltsz": 2e10, "hs": 3.30, "zbc": 1, "hybk": "化学制药"},
            ]
        elif "getTopicDTPool" in path:
            tc, pool = 1, [
                {"c": "600156", "n": "华升股份", "p": 7350, "zdp": -10.04, "amount": 314199664,
                 "ltsz": 3e9, "hs": 12.0, "hybk": "纺织制造"},
            ]
        else:  # getTopicQSPool
            tc, pool = 1, [
                {"c": "300746", "n": "汉嘉数智", "p": 14870, "zdp": -11.54, "amount": 344154896,
                 "ltsz": 3e9, "hs": 15.0, "hybk": "工程咨询"},
            ]
        body = json.dumps({"data": {"tc": tc, "pool": pool}}, ensure_ascii=False)
        return FakeFetched(body)


class TestRadar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.store.init_schema()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_run_radar(self):
        res = run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["by_pool"], {"up": 2, "break": 1, "down": 1, "strong": 1})
        self.assertEqual(res["written"], 5)
        self.assertEqual(self.store.count_limit_up(TRADE_DATE), 5)
        self.assertEqual(self.store.count_limit_up(TRADE_DATE, "up"), 2)

    def test_ladder_distribution(self):
        run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        rows = self.store.ladder_distribution(TRADE_DATE)
        got = {r["ladder"]: r["n"] for r in rows}
        # 1 板 1 只 + 4 板 1 只
        self.assertEqual(got, {4: 1, 1: 1})

    def test_fields_stored(self):
        run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        r = self.store.conn.execute(
            "SELECT name, pct_chg, turnover, industry, ladder FROM limit_up "
            "WHERE stock_code='603127' AND pool_type='up'"
        ).fetchone()
        self.assertEqual(r["name"], "昭衍新药")
        self.assertAlmostEqual(r["pct_chg"], 10.0)
        self.assertAlmostEqual(r["turnover"], 8.83)
        self.assertEqual(r["industry"], "医疗服务")
        self.assertEqual(r["ladder"], 1)

    def test_idempotent(self):
        run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        res = run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        self.assertEqual(res["status"], "skipped")

    def test_render_radar(self):
        run_radar(self.store, _PoolFakeHttp(), trade_date=TRADE_DATE)
        out = Path(self.tmp.name) / "dist"
        SiteBuilder(self.store, out).build(TRADE_DATE)
        self.assertTrue((out / "radar" / "index.html").exists())
        self.assertTrue((out / "en" / "radar" / "index.html").exists())
        html = (out / "radar" / "index.html").read_text(encoding="utf-8")
        self.assertIn("资金雷达", html)
        self.assertIn("昭衍新药", html)
        self.assertIn("连板梯队", html)

    def test_pool_sort_keys(self):
        """不同池用不同 sort 字段（用错会返回空，这是实测踩过的坑）。"""
        from tidewatch.datasource.eastmoney import _POOL_ENDPOINT

        self.assertEqual(_POOL_ENDPOINT["up"][1], "fbt:asc")
        self.assertEqual(_POOL_ENDPOINT["down"][1], "zdp:asc")
        self.assertNotEqual(_POOL_ENDPOINT["up"][1], _POOL_ENDPOINT["down"][1])


if __name__ == "__main__":
    unittest.main()
