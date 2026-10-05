"""个股数据管道：全市场快照 → stock_daily。

数据源：东财 clist 批量（DESIGN §4.2，2026-10-05 实测 total≈5921）。
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

log = get_logger("pipeline.stocks")
SCHEMA_VERSION = "em-stock-v1"
ALGORITHM_VERSION = "stocks-v1"


def _hash(obj: object) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_stocks(
    store: Store,
    http: HttpClient,
    *,
    trade_date: str | None = None,
    force: bool = False,
    max_stocks: int = 800,
) -> dict:
    """抓个股快照。

    `max_stocks=800`（默认）：按成交额降序只抓前 800（≈ 8 页）。
    **不要改成 None（全市场 60 页）**——实测会触发东财限流封 IP（DESIGN §4.7）。
    """
    provider = "eastmoney"
    target = resolve_target_date(trade_date)
    if not cal.is_trading_day(date.fromisoformat(target)):
        raise ValueError(f"target date {target} is not a trading day")

    if not force and store.is_done("stocks", target, ALGORITHM_VERSION):
        log.info("already done: stocks %s", target)
        return {"status": "skipped", "target": target, "written": 0}

    run_id = store.begin_run(
        "stocks", trade_date=target, provider=provider, algorithm_version=ALGORITHM_VERSION
    )
    src = EastmoneySource(http)
    written = 0
    try:
        quotes = src.all_stocks(max_stocks=max_stocks)
        avail = now_beijing().isoformat()
        with store.transaction():
            for q in quotes:
                if not q.stock_code:
                    continue
                store.upsert_stock_daily({
                    "stock_code": q.stock_code, "trade_date": target,
                    "name": q.name, "close": q.close, "pct_chg": q.pct_chg,
                    "turnover": q.turnover, "amount": q.amount,
                    "pe_ttm": q.pe_ttm, "pb": q.pb,
                    "total_mcap": q.total_mcap, "float_mcap": q.float_mcap,
                    "source_provider": provider, "available_at": avail,
                    "input_hash": _hash([target, q.stock_code, q.close, q.amount]),
                    "algorithm_version": ALGORITHM_VERSION,
                })
                written += 1

        status = "success" if written else "failed"
        store.finish_run(
            run_id, status, domain=src.last_host, row_count=written,
            schema_version=SCHEMA_VERSION,
            error_message=None if written else "no stock quotes",
        )
        log.info("stocks done: %d (target=%s)", written, target)
        return {"status": status, "target": target, "written": written}

    except Exception as exc:  # noqa: BLE001
        store.finish_run(run_id, "failed", error_class=type(exc).__name__,
                         error_message=str(exc)[:500])
        log.error("stocks failed: %s", exc)
        raise
