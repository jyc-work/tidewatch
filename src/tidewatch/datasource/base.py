"""数据源抽象接口（DESIGN §4.6）。

实现之间可互换：ths（同花顺，P0 主力）/ eastmoney（东财）/ qmt（可选补充）。
每个返回的序列都必须带 provider 标记，避免不同源被拼成同一条曲线（§6.4）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SectorInfo:
    sector_code: str
    name: str
    category: str          # industry | concept
    provider: str


@dataclass
class Kline:
    date: str              # YYYYMMDD 或 YYYY-MM-DD（统一由使用方规整）
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


class SectorSource(Protocol):
    name: str

    def list_sectors(self, category: str) -> list[SectorInfo]:
        """列出某类板块（industry / concept）。"""
        ...

    def sector_kline(self, sector_code: str) -> list[Kline]:
        """返回按时间升序的板块指数 K 线。"""
        ...
