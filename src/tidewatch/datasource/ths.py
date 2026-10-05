"""同花顺板块数据源（P0 主力源，实测可用）。

接口（2026-10-05 实测）：
    板块列表   http://q.10jqka.com.cn/thshy/   行业（140 个，代码 881xxx）
               http://q.10jqka.com.cn/gn/      概念（361 个，代码 30xxxx/3xxxxx）
    板块 K 线  https://d.10jqka.com.cn/v6/line/bk_{code}/01/last.js  （JSONP）

last.js 结构：
    quotebridge_v6_line_bk_881101_01_last({
      "name": "种植业与林业", "total": 4628, "num": 140, "today": 20261005,
      "data": "20260311,开,高,低,收,量,额,,,,0;20260312,..."
    })
    每段字段：date, open, high, low, close, volume, amount, ...(空), 0
"""
from __future__ import annotations

import json
import re

from ..http import HttpClient
from .base import Kline, SectorInfo

_JSONP = re.compile(r"\((.*)\)\s*;?\s*$", re.S)
# 概念板块：列表页内嵌 gnSection JSON，含 platecode(885xxx，K线可用) + platename
_GN_SECTION = re.compile(r'id="gnSection"\s+value=\'([^\']+)\'', re.S)
_LIST_CODE = {
    # 行业：同时捕获代码与名称，避免额外请求拿板块名
    "industry": re.compile(r"/thshy/detail/code/(\d+)/[^>]*>([^<]{1,30})<"),
    "concept": re.compile(r"/gn/detail/code/(\d+)/[^>]*>([^<]{1,30})<"),
}
_LIST_URL = {
    "industry": "/thshy/",
    "concept": "/gn/",
}
_HOSTS = ["q.10jqka.com.cn"]
_LINE_HOSTS = ["d.10jqka.com.cn"]


def _to_float(x: str) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


class ThsSource:
    name = "ths"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    # ---------------- 板块列表 ----------------
    def list_sectors(self, category: str) -> list[SectorInfo]:
        if category not in _LIST_CODE:
            raise ValueError(f"unknown category: {category}")
        f = self.http.get_with_fallback(_HOSTS, _LIST_URL[category])

        # 概念板块：解析内嵌 gnSection JSON，拿到 885xxx（K线可用）
        if category == "concept":
            m = _GN_SECTION.search(f.text)
            if not m:
                raise ValueError("gnSection not found in concept list page")
            data = json.loads(m.group(1))
            seen_c: set[str] = set()
            items: list[tuple[float, str, str]] = []
            for v in data.values():
                code, name = v.get("platecode"), v.get("platename")
                if not code or not name or code in seen_c:
                    continue
                seen_c.add(code)
                # zjjlr = 当日资金净流入（亿），以其绝对值做热度排序
                heat = abs(float(v.get("zjjlr") or 0))
                items.append((heat, code, name.strip()))
            items.sort(key=lambda t: t[0], reverse=True)
            return [SectorInfo(c, n, category, self.name) for _, c, n in items]

        # 行业板块：从 a 标签提取代码与名称
        seen: set[str] = set()
        out = []
        for code, name in _LIST_CODE[category].findall(f.text):
            if code in seen:
                continue
            seen.add(code)
            out.append(SectorInfo(code, name.strip(), category, self.name))
        return out

    # ---------------- 板块 K 线 ----------------
    def fetch_sector(self, sector_code: str) -> tuple[str, list[Kline]]:
        """一次请求同时拿到板块名与 K 线（last.js 两者都含，避免重复请求）。"""
        path = f"/v6/line/bk_{sector_code}/01/last.js"
        f = self.http.get_with_fallback(_LINE_HOSTS, path)
        m = _JSONP.search(f.text.strip())
        if not m:
            raise ValueError(f"unexpected last.js format for {sector_code}")
        obj = json.loads(m.group(1))
        name = obj.get("name", "")
        rows: list[Kline] = []
        for seg in obj.get("data", "").split(";"):
            parts = seg.split(",")
            if len(parts) < 7 or not parts[0]:
                continue
            rows.append(
                Kline(
                    date=parts[0],
                    open=_to_float(parts[1]),
                    high=_to_float(parts[2]),
                    low=_to_float(parts[3]),
                    close=_to_float(parts[4]),
                    volume=_to_float(parts[5]),
                    amount=_to_float(parts[6]),
                )
            )
        rows.sort(key=lambda k: k.date)
        return name, rows

    def sector_kline(self, sector_code: str) -> list[Kline]:
        return self.fetch_sector(sector_code)[1]
