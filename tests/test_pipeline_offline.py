"""板块管道离线全链路测试（§10.1 验收项 #1 幂等 / #5 日期校验 / #8 离线）。

全部基于 tests/fixtures，不联网。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tidewatch.compute.momentum import ALGORITHM_VERSION
from tidewatch.pipeline.sectors import run_sectors
from tidewatch.store.db import Store
from tests.helpers import kline_fake

TARGET = "2026-09-30"          # fixtures 里 K 线的最后交易日
CODES = ["881101", "881121", "881273"]


class TestSectorsOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.store.init_schema()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_full_run(self):
        res = run_sectors(
            self.store, kline_fake(),
            sector_codes=CODES, category="industry", target_date=TARGET,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["written"], 3)
        self.assertEqual(self.store.count_sector_daily(TARGET), 3)

        row = self.store.get_sector_daily("881121", TARGET)
        self.assertIsNotNone(row)
        self.assertEqual(row["source_provider"], "ths")
        self.assertEqual(row["calculation_method"], "index_direct")
        self.assertEqual(row["algorithm_version"], ALGORITHM_VERSION)
        self.assertIn(row["stage"], ("持续领涨", "高位回落", "超跌反弹", "持续走弱"))
        self.assertGreater(row["amount"], 0)

    def test_idempotent(self):
        r1 = run_sectors(self.store, kline_fake(), sector_codes=CODES,
                         category="industry", target_date=TARGET)
        self.assertEqual(r1["status"], "success")
        # 第二次应跳过（幂等，验收项 #1）
        r2 = run_sectors(self.store, kline_fake(), sector_codes=CODES,
                         category="industry", target_date=TARGET)
        self.assertEqual(r2["status"], "skipped")

    def test_force_rerun_stable(self):
        run_sectors(self.store, kline_fake(), sector_codes=CODES,
                    category="industry", target_date=TARGET)
        first = dict(self.store.get_sector_daily("881121", TARGET))
        run_sectors(self.store, kline_fake(), sector_codes=CODES,
                    category="industry", target_date=TARGET, force=True)
        second = dict(self.store.get_sector_daily("881121", TARGET))
        # 重跑结果确定：指标与 input_hash 完全一致
        for k in ("ret_1d", "ret_5d", "ret_20d", "close", "input_hash", "stage"):
            self.assertEqual(first[k], second[k], f"field {k} changed on rerun")

    def test_date_mismatch_rejected(self):
        """数据日期 ≠ 目标交易日时必须跳过（验收项 #5）。

        fixture 数据最后一天是 2026-09-30；目标设为 09-29（交易日）→ 应全部跳过。
        """
        res = run_sectors(self.store, kline_fake(), sector_codes=CODES,
                          category="industry", target_date="2026-09-29")
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["written"], 0)
        self.assertTrue(all("date" in why for _, why in res["skipped"]))

    def test_non_trading_day_raises(self):
        """非交易日拒绝出数（验收项 #4）。2026-10-01 是国庆。"""
        with self.assertRaises(ValueError):
            run_sectors(self.store, kline_fake(), sector_codes=CODES,
                        category="industry", target_date="2026-10-01")


if __name__ == "__main__":
    unittest.main()
