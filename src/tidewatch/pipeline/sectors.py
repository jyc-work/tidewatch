"""板块管道：抓取 → 校验 → 计算 → 原子落库（幂等）。

对应 DESIGN §6.3 的 9 步流程（P0 实现 1–5，渲染在 P1）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .. import calendar as cal
from ..compute.momentum import ALGORITHM_VERSION, classify_stage, returns_from_closes
from ..datasource.ths import ThsSource
from ..http import HttpClient
from ..store.db import Store
from ..utils import get_logger, now_beijing

log = get_logger("pipeline.sectors")
SCHEMA_VERSION = "ths-v1"
SOURCE_HOST = "d.10jqka.com.cn"


def norm_date(d: str) -> str:
    """20260311 -> 2026-03-11"""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def _hash(obj: object) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_target_date(explicit: str | None = None) -> str:
    """目标交易日：显式指定，或「最近一个已收盘的交易日」。"""
    if explicit:
        return explicit
    now = now_beijing()
    d = now.date()
    if cal.is_trading_day(d) and now.hour >= 15:
        return d.isoformat()
    return cal.prev_trading_day(d).isoformat()


def run_sectors(
    store: Store,
    http: HttpClient,
    *,
    sector_codes: list[str],
    category: str = "industry",
    target_date: str | None = None,
    force: bool = False,
) -> dict:
    provider = "ths"
    target = resolve_target_date(target_date)

    # 验收项 #4：非交易日拒绝出数
    if not cal.is_trading_day(date.fromisoformat(target)):
        raise ValueError(f"target date {target} is not a trading day")

    # 幂等（§6.3）：部分重跑（先 3 个后 90 个）不能被误判为已完成
    if not force and store.is_done("sectors", target, ALGORITHM_VERSION,
                                   expected_count=len(sector_codes)):
        log.info("already done: sectors %s %s", target, ALGORITHM_VERSION)
        return {"status": "skipped", "target": target, "written": 0, "skipped": []}

    run_id = store.begin_run(
        "sectors", trade_date=target, provider=provider, algorithm_version=ALGORITHM_VERSION
    )
    src = ThsSource(http)
    written = 0
    skipped: list[tuple[str, str]] = []

    try:
        with store.transaction():
            for code in sector_codes:
                # 单个板块失败（如 502/无数据）不应中断整批
                try:
                    name, klines = src.fetch_sector(code)
                except Exception as exc:  # noqa: BLE001
                    skipped.append((code, f"fetch error: {str(exc)[:80]}"))
                    continue
                if not klines:
                    skipped.append((code, "empty"))
                    continue
                last = norm_date(klines[-1].date)
                # 验收项 #5：数据日期必须等于目标交易日
                if last != target:
                    skipped.append((code, f"date {last} != {target}"))
                    continue

                closes = [k.close for k in klines]
                rets = returns_from_closes(closes, (1, 5, 20))
                rec = {
                    "sector_code": code,
                    "trade_date": target,
                    "close": closes[-1],
                    "ret_1d": rets[1],
                    "ret_5d": rets[5],
                    "ret_20d": rets[20],
                    "stage": classify_stage(rets[20], rets[1]),
                    "amount": klines[-1].amount,
                    "source_provider": provider,
                    "source_symbol": f"bk_{code}",
                    "calculation_method": "index_direct",
                    "member_snapshot_id": None,
                    "available_at": now_beijing().isoformat(),
                    "input_hash": _hash([(k.date, k.close) for k in klines[-25:]]),
                    "algorithm_version": ALGORITHM_VERSION,
                }
                store.upsert_sector(code, name, category)
                store.upsert_sector_daily(rec)
                written += 1

        status = "success" if written else "failed"
        store.finish_run(
            run_id,
            status,
            domain=SOURCE_HOST,
            row_count=written,
            schema_version=SCHEMA_VERSION,
            error_message=None if written else "no sectors written",
        )
        log.info("sectors done: %d written, %d skipped (target=%s)", written, len(skipped), target)
        return {"status": status, "target": target, "written": written, "skipped": skipped}

    except Exception as exc:  # noqa: BLE001 - 记录后重新抛出
        store.finish_run(
            run_id, "failed", error_class=type(exc).__name__, error_message=str(exc)[:500]
        )
        log.error("sectors failed: %s", exc)
        raise
