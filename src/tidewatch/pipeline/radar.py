"""资金雷达管道：涨停池 / 炸板池 / 跌停池 / 强势股池 → limit_up。

数据源：东财 push2ex（DESIGN §4.2，2026-10-05 实测）。
注意「资金雷达」不是传统四层资金流，口径差异已在 §3.2 说明。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .. import calendar as cal
from ..datasource.eastmoney import EastmoneySource
from ..http import HttpClient
from ..store.db import Store
from ..utils import get_logger
from .sectors import resolve_target_date

log = get_logger("pipeline.radar")
SCHEMA_VERSION = "em-pool-v1"
ALGORITHM_VERSION = "radar-v1"
POOLS = ("up", "break", "down", "strong")


def _hash(obj: object) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_radar(
    store: Store,
    http: HttpClient,
    *,
    trade_date: str | None = None,
    force: bool = False,
    pools: tuple[str, ...] = POOLS,
) -> dict:
    provider = "eastmoney"
    target = resolve_target_date(trade_date)
    if not cal.is_trading_day(date.fromisoformat(target)):
        raise ValueError(f"target date {target} is not a trading day")

    if not force and store.is_done("radar", target, ALGORITHM_VERSION):
        log.info("already done: radar %s", target)
        return {"status": "skipped", "target": target, "written": 0, "by_pool": {}}

    run_id = store.begin_run(
        "radar", trade_date=target, provider=provider, algorithm_version=ALGORITHM_VERSION
    )
    src = EastmoneySource(http)
    written = 0
    by_pool: dict[str, int] = {}

    try:
        with store.transaction():
            for pt in pools:
                try:
                    rows = src.limit_pool(target, pt)
                except Exception as exc:  # noqa: BLE001
                    log.warning("pool %s fetch failed: %s", pt, exc)
                    by_pool[pt] = 0
                    continue
                by_pool[pt] = len(rows)
                for r in rows:
                    store.upsert_limit_up(
                        trade_date=target, stock_code=r.stock_code, pool_type=pt,
                        name=r.name, pct_chg=r.pct_chg, turnover=r.turnover,
                        industry=r.industry, ladder=r.ladder, amount=r.amount,
                        source_provider=provider,
                        input_hash=_hash([target, r.stock_code, pt, r.ladder, r.amount]),
                    )
                    written += 1

        status = "success" if written else "failed"
        store.finish_run(
            run_id, status, domain=src.last_host, row_count=written,
            schema_version=SCHEMA_VERSION,
            error_message=None if written else "no pool records",
        )
        log.info("radar done: %d records %s (target=%s)", written, by_pool, target)
        return {"status": status, "target": target, "written": written, "by_pool": by_pool}

    except Exception as exc:  # noqa: BLE001
        store.finish_run(run_id, "failed", error_class=type(exc).__name__,
                         error_message=str(exc)[:500])
        log.error("radar failed: %s", exc)
        raise
