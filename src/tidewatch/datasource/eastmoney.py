"""东方财富数据源：龙虎榜（席位明细）。

接口（datacenter-web，2026-10-05 实测可用）：
    reportName=RPT_BILLBOARD_DAILYDETAILSBUY   买入席位
    reportName=RPT_BILLBOARD_DAILYDETAILSSELL  卖出席位

关键字段：
    TRADE_DATE / SECURITY_CODE / OPERATEDEPT_CODE / OPERATEDEPT_NAME
    BUY / SELL / EXPLANATION / CHANGE_RATE / CLOSE_PRICE

注意：`OPERATEDEPT_CODE` 作为席位主键（DESIGN §6.2 / 评审点 4），
名称会因券商合并更名而变化，不能做长期主键。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..http import HttpClient

_HOSTS = ["datacenter-web.eastmoney.com"]
_PATH = "/api/data/v1/get"
# 行情/列表接口在 push2 域名（不是 datacenter-web）
# 实测：clist 在 push2delay 上会 RemoteDisconnected，故不列它
_QUOTE_HOSTS = ["push2.eastmoney.com"]
_PAGE_SIZE = 500
_REPORT = {
    "buy": "RPT_BILLBOARD_DAILYDETAILSBUY",
    "sell": "RPT_BILLBOARD_DAILYDETAILSSELL",
}


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class SeatRecord:
    trade_date: str
    stock_code: str
    operatedept_code: str
    operatedept_name: str
    side: str
    buy: float
    sell: float
    reason: str
    change_rate: float | None


@dataclass
class PoolStock:
    """涨停/炸板/跌停/强势股池条目。"""

    stock_code: str
    name: str
    pool_type: str          # up | break | down | strong
    price: float
    pct_chg: float
    amount: float
    turnover: float         # 换手率 %
    float_mcap: float       # 流通市值
    ladder: int             # 连板数（涨停池 lbc；其余 0）
    seal_fund: float        # 封单资金（fund）
    break_times: int        # 炸板次数（zbc）
    industry: str           # 所属行业（hybk）


@dataclass
class StockQuote:
    """个股快照（全市场批量）。"""

    stock_code: str
    name: str
    close: float
    pct_chg: float
    amount: float
    turnover: float
    pe_ttm: float | None
    pb: float | None
    total_mcap: float
    float_mcap: float


# 涨跌停池接口（push2ex，2026-10-05 实测）
# 注意：不同池需要不同的 sort 字段，用错会返回空数据
_POOL_HOSTS = ["push2ex.eastmoney.com"]
_POOL_UT = "7eea3edcaed734bea9cbfc24409ed989"
_POOL_ENDPOINT = {
    "up": ("getTopicZTPool", "fbt:asc"),
    "break": ("getTopicZBPool", "fbt:asc"),
    "down": ("getTopicDTPool", "zdp:asc"),
    "strong": ("getTopicQSPool", "zdp:asc"),
}


def _i(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# 全市场股票（沪深主板 + 创业板 + 科创板 + 北交所）
_STOCK_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_STOCK_FIELDS = "f12,f14,f2,f3,f5,f6,f8,f9,f23,f20,f21,f115"


def _num_or_none(v) -> float | None:
    """东财用 '-' 表示无值（如亏损股 PE）。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class EastmoneySource:
    name = "eastmoney"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.last_host = _HOSTS[0]

    # ---------------- 全市场个股 ----------------
    def all_stocks(self, *, page_size: int = 100) -> list[StockQuote]:
        """批量拉全市场个股快照（约 5900 只，60 页）。

        注意：`fs` 参数含 `+`（东财的分隔符），**不能交给 requests 编码**，
        否则 `+` → `%2B`，东财会拒绝。所以 query 手工拼接。
        """
        from urllib.parse import urlencode

        out: list[StockQuote] = []
        page = 1
        while True:
            qs = urlencode({
                "pn": page, "pz": page_size, "po": 1, "np": 1,
                "fltt": 2, "invt": 2, "fid": "f3",
            })
            path = (f"/api/qt/clist/get?{qs}&fs={_STOCK_FS}&fields={_STOCK_FIELDS}")
            f = self.http.get_with_fallback(_QUOTE_HOSTS, path)
            self.last_host = f.host
            data = (f.json() or {}).get("data") or {}
            diff = data.get("diff") or []
            for r in diff:
                out.append(StockQuote(
                    stock_code=str(r.get("f12") or ""),
                    name=str(r.get("f14") or ""),
                    close=_f(r.get("f2")),
                    pct_chg=_f(r.get("f3")),
                    amount=_f(r.get("f6")),
                    turnover=_f(r.get("f8")),
                    pe_ttm=_num_or_none(r.get("f115")),
                    pb=_num_or_none(r.get("f23")),
                    total_mcap=_f(r.get("f20")),
                    float_mcap=_f(r.get("f21")),
                ))
            total = int(data.get("total") or 0)
            if not diff or page * page_size >= total:
                break
            page += 1
        return out

    # ---------------- 涨跌停池 ----------------
    def limit_pool(self, trade_date: str, pool_type: str = "up") -> list[PoolStock]:
        """抓某个池（up/break/down/strong）当日全部标的。"""
        if pool_type not in _POOL_ENDPOINT:
            raise ValueError(f"unknown pool_type: {pool_type}")
        endpoint, sort = _POOL_ENDPOINT[pool_type]
        d = trade_date.replace("-", "")
        out: list[PoolStock] = []
        page = 0
        while True:
            params = {
                "ut": _POOL_UT, "dpt": "wz.ztzt", "Pageindex": page,
                "pagesize": 100, "sort": sort, "date": d,
            }
            f = self.http.get_with_fallback(_POOL_HOSTS, f"/{endpoint}", params=params)
            self.last_host = f.host
            data = (f.json() or {}).get("data") or {}
            pool = data.get("pool") or []
            for r in pool:
                out.append(PoolStock(
                    stock_code=str(r.get("c") or ""),
                    name=str(r.get("n") or ""),
                    pool_type=pool_type,
                    price=_f(r.get("p")) / 100.0,       # 分 -> 元
                    pct_chg=_f(r.get("zdp")),
                    amount=_f(r.get("amount")),
                    turnover=_f(r.get("hs")),
                    float_mcap=_f(r.get("ltsz")),
                    ladder=_i(r.get("lbc")),
                    seal_fund=_f(r.get("fund")),
                    break_times=_i(r.get("zbc")),
                    industry=str(r.get("hybk") or ""),
                ))
            total = _i(data.get("tc"))
            if not pool or (page + 1) * 100 >= total:
                break
            page += 1
        return out

    def _datacenter(self, report: str, *, filt: str, page: int = 1) -> list[dict]:
        params = {
            "reportName": report,
            "columns": "ALL",
            "pageNumber": page,
            "pageSize": _PAGE_SIZE,
            "source": "WEB",
            "client": "WEB",
            "filter": filt,
        }
        f = self.http.get_with_fallback(_HOSTS, _PATH, params=params)
        self.last_host = f.host
        d = f.json()
        result = (d or {}).get("result") or {}
        return result.get("data") or []

    def lhb_seats(self, trade_date: str, side: str = "buy") -> list[SeatRecord]:
        """抓某交易日某方向（buy/sell）的全部龙虎榜席位明细。"""
        report = _REPORT[side]
        filt = f"(TRADE_DATE='{trade_date}')"
        out: list[SeatRecord] = []
        page = 1
        while True:
            rows = self._datacenter(report, filt=filt, page=page)
            if not rows:
                break
            for r in rows:
                code = str(r.get("OPERATEDEPT_CODE") or "").strip()
                name = str(r.get("OPERATEDEPT_NAME") or "").strip()
                if not code or not name:
                    continue
                out.append(
                    SeatRecord(
                        trade_date=str(r.get("TRADE_DATE", ""))[:10],
                        stock_code=str(r.get("SECURITY_CODE") or "").strip(),
                        operatedept_code=code,
                        operatedept_name=name,
                        side=side,
                        buy=_f(r.get("BUY")),
                        sell=_f(r.get("SELL")),
                        reason=str(r.get("EXPLANATION") or "").strip(),
                        change_rate=(_f(r["CHANGE_RATE"]) if r.get("CHANGE_RATE") is not None else None),
                    )
                )
            if len(rows) < _PAGE_SIZE:
                break
            page += 1
        return out
