"""龙虎榜管道 + 游资页测试（离线，用 FakeHttp 造东财响应）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tidewatch.pipeline.lhb import run_lhb
from tidewatch.render.builder import SiteBuilder
from tidewatch.store.db import Store
from tests.helpers import FakeHttp

TRADE_DATE = "2026-09-30"


def _em_row(code, name, stock, side):
    return {
        "TRADE_DATE": f"{TRADE_DATE} 00:00:00",
        "SECURITY_CODE": stock,
        "OPERATEDEPT_CODE": code,
        "OPERATEDEPT_NAME": name,
        "BUY": 100000000.0 if side == "buy" else 50000000.0,
        "SELL": 50000000.0 if side == "buy" else 100000000.0,
        "EXPLANATION": "test",
        "CHANGE_RATE": 10.0,
    }


class _EmFakeHttp:
    """模拟东财 datacenter 响应（按 reportName 区分）。"""

    def __init__(self) -> None:
        self.calls = 0

    def get_with_fallback(self, hosts, path, *, params=None, headers=None):
        self.calls += 1
        report = (params or {}).get("reportName", "")
        side = "buy" if "BUY" in report else "sell"
        rows = [
            _em_row("10434470", "沪股通专用", "600000", side),
            _em_row("10025390", "国泰海通证券股份有限公司北京知春路证券营业部", "000001", side),
        ]
        body = json.dumps({"result": {"pages": 1, "data": rows}}, ensure_ascii=False)
        from tests.helpers import FakeFetched

        return FakeFetched(body, host="datacenter-web.eastmoney.com")


class TestLhb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.store.init_schema()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_run_lhb(self):
        res = run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        self.assertEqual(res["status"], "success")
        # 2 席位 × 2 方向
        self.assertEqual(res["written"], 4)
        self.assertEqual(res["seats"], 2)
        self.assertEqual(self.store.count_lhb(TRADE_DATE), 4)

    def test_seat_uses_code_as_key(self):
        run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        rows = self.store.conn.execute(
            "SELECT operatedept_code, seat_name, activity_evidence, identity_evidence FROM seat"
        ).fetchall()
        codes = {r["operatedept_code"] for r in rows}
        self.assertEqual(codes, {"10434470", "10025390"})
        for r in rows:
            self.assertEqual(r["activity_evidence"], "measured")
            # 未证实身份一律 unknown（证据分层，评审点 4）
            self.assertEqual(r["identity_evidence"], "unknown")

    def test_seat_name_change_keeps_code(self):
        """席位更名后仍归入同一 operatedept_code（验收项 #7）。"""
        run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        self.store.upsert_seat(operatedept_code="10434470", seat_name="沪股通专用（更名）")
        rows = self.store.conn.execute(
            "SELECT seat_name, last_seen_name FROM seat WHERE operatedept_code='10434470'"
        ).fetchall()
        self.assertEqual(len(rows), 1, "code must stay unique")
        self.assertEqual(rows[0]["seat_name"], "沪股通专用（更名）")

    def test_idempotent(self):
        run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        res = run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        self.assertEqual(res["status"], "skipped")

    def test_render_people(self):
        run_lhb(self.store, _EmFakeHttp(), trade_date=TRADE_DATE)
        out = Path(self.tmp.name) / "dist"
        res = SiteBuilder(self.store, out).build(TRADE_DATE)
        # 每语言：首页 + 板块列表 + 游资列表 = 3；无板块数据故板块详情为 0
        # 游资详情 2 个席位 × 2 语言
        self.assertTrue((out / "people" / "index.html").exists())
        self.assertTrue((out / "en" / "people" / "index.html").exists())
        self.assertTrue((out / "people" / "10434470" / "index.html").exists())
        html = (out / "people" / "index.html").read_text(encoding="utf-8")
        # 有社区别名的席位显示别名，无别名则显示全名
        self.assertIn("沪股通", html)
        self.assertIn("北京知春路", html)


if __name__ == "__main__":
    unittest.main()
