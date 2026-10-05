"""A 股交易日历：周末 + 内置节假日表。

迁移自 daily-review/market_calendar.py，简化为仅 CN。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .utils import get_logger, now_beijing

log = get_logger("calendar")
_HOLIDAYS: set[str] | None = None
_HOLIDAYS_PATH = Path(__file__).resolve().parent / "holidays_cn.json"


def _load() -> set[str]:
    global _HOLIDAYS
    if _HOLIDAYS is None:
        data = json.loads(_HOLIDAYS_PATH.read_text(encoding="utf-8"))
        s: set[str] = set()
        for dates in data.values():
            s.update(dates)
        _HOLIDAYS = s
    return _HOLIDAYS


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in _load()


def is_trading_day_today() -> bool:
    return is_trading_day(now_beijing().date())


def prev_trading_day(d: date) -> date:
    """返回 d 之前（不含 d）最近的一个交易日。"""
    from datetime import timedelta

    cur = d - timedelta(days=1)
    for _ in range(30):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    raise RuntimeError("could not find a previous trading day within 30 days")
