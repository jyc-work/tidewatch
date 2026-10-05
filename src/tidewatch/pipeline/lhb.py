"""龙虎榜管道：抓取 → 落库（lhb_record + seat）。

数据源：东财 datacenter（DESIGN §4.2 接口 6/7/8）。
席位主键用 `operatedept_code`，名称仅作展示（券商合并会改名，评审点 4）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .. import calendar as cal
from ..datasource.eastmoney import EastmoneySource
from ..http import HttpClient
from ..store.db import Store
from ..utils import get_logger, now_beijing
from .sectors import resolve_target_date

log = get_logger("pipeline.lhb")
SCHEMA_VERSION = "em-lhb-v1"
ALGORITHM_VERSION = "lhb-v1"


def _hash(obj: object) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_lhb(
    store: Store,
    http: HttpClient,
    *,
    trade_date: str | None = None,
    force: bool = False,
) -> dict:
    provider = "eastmoney"
    target = resolve_target_date(trade_date)
    if not cal.is_trading_day(date.fromisoformat(target)):
        raise ValueError(f"target date {target} is not a trading day")

    if not force and store.is_done("lhb", target, ALGORITHM_VERSION):
        log.info("already done: lhb %s", target)
        return {"status": "skipped", "target": target, "written": 0, "seats": 0}

    run_id = store.begin_run(
        "lhb", trade_date=target, provider=provider, algorithm_version=ALGORITHM_VERSION
    )
    src = EastmoneySource(http)
    written = 0
    seats: set[str] = set()

    try:
        with store.transaction():
            for side in ("buy", "sell"):
                try:
                    records = src.lhb_seats(target, side)
                except Exception as exc:  # noqa: BLE001
                    log.warning("lhb %s fetch failed: %s", side, exc)
                    continue
                for r in records:
                    amount = r.buy if side == "buy" else r.sell
                    store.upsert_lhb_record(
                        trade_date=r.trade_date, stock_code=r.stock_code,
                        operatedept_code=r.operatedept_code, side=side,
                        amount=amount, reason=r.reason,
                        source_provider=provider,
                        input_hash=_hash([r.trade_date, r.stock_code,
                                          r.operatedept_code, side, amount]),
                    )
                    store.upsert_seat(
                        operatedept_code=r.operatedept_code,
                        seat_name=r.operatedept_name,
                        source_query=f"{'RPT_BILLBOARD_DAILYDETAILS' + side.upper()}",
                    )
                    written += 1
                    seats.add(r.operatedept_code)

        status = "success" if written else "failed"
        store.finish_run(
            run_id, status, domain=src.last_host, row_count=written,
            schema_version=SCHEMA_VERSION,
            error_message=None if written else "no lhb records",
        )
        log.info("lhb done: %d records, %d seats (target=%s)", written, len(seats), target)
        return {"status": status, "target": target, "written": written, "seats": len(seats)}

    except Exception as exc:  # noqa: BLE001
        store.finish_run(run_id, "failed", error_class=type(exc).__name__,
                         error_message=str(exc)[:500])
        log.error("lhb failed: %s", exc)
        raise
