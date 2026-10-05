"""静态站构建：SQLite → dist/（中英双语，DESIGN §7.4 / §8）。

页面：
    /                     首页（中文）
    /en/                  首页（英文）
    /sectors/             板块图谱
    /en/sectors/
    /sectors/{code}/      板块详情
    /en/sectors/{code}/
    /assets/style.css
"""
from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

import yaml

from ..store.db import Store
from .i18n import DEFAULT, SUPPORTED, I18n, locale_prefix

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_ASSETS = _HERE / "assets"
_SEATS_YAML = _HERE.parents[2] / "mapping" / "seats.yaml"

STAGE_CLS = {"持续领涨": "s1", "高位回落": "s2", "超跌反弹": "s3", "持续走弱": "s4"}


def _load_seat_aliases() -> dict[str, str]:
    """从 mapping/seats.yaml 读走席位别名（仅展示用，不声称身份）。"""
    if not _SEATS_YAML.exists():
        return {}
    try:
        data = yaml.safe_load(_SEATS_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    out: dict[str, str] = {}
    for s in data.get("seats", []):
        code, alias = s.get("operatedept_code"), s.get("alias")
        if code and alias:
            out[str(code)] = alias
    return out


def _cls(v: float | None) -> str:
    if v is None:
        return "flat"
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def _pct(v: float | None) -> str:
    return f"{v * 100:+.2f}%" if v is not None else "-"


def _num(v: float | None, nd: int = 2) -> str:
    return f"{v:.{nd}f}" if v is not None else "-"


class SiteBuilder:
    def __init__(self, store: Store, out_dir, *, base_url: str = "https://localhost",
                 base_path: str = "") -> None:
        self.store = store
        self.out = Path(out_dir)
        self.base_url = base_url.rstrip("/")
        # GitHub Pages 项目站点挂在 /<repo>/ 子路径下，需带上前缀
        bp = (base_path or "").strip()
        self.base_path = "" if bp in ("", "/") else "/" + bp.strip("/")
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ---------------- 数据准备 ----------------
    def _rows(self, trade_date: str, i18n: I18n) -> list[dict]:
        rows = self.store.conn.execute(
            "SELECT sd.sector_code, sd.close, sd.ret_1d, sd.ret_5d, sd.ret_20d, sd.stage, "
            "sd.amount, s.name FROM sector_daily sd JOIN sector s USING(sector_code) "
            "WHERE sd.trade_date=? ORDER BY COALESCE(sd.amount, 0) DESC",
            (trade_date,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "code": r["sector_code"],
                "name": i18n.sector_name(r["sector_code"], r["name"]),
                "close_text": _num(r["close"]),
                "ret1_text": _pct(r["ret_1d"]), "cls1": _cls(r["ret_1d"]),
                "ret5_text": _pct(r["ret_5d"]), "cls5": _cls(r["ret_5d"]),
                "ret20_text": _pct(r["ret_20d"]), "cls20": _cls(r["ret_20d"]),
                "stage_text": i18n.stage(r["stage"]),
                "stage_cls": STAGE_CLS.get(r["stage"] or "", ""),
                "amount_text": _num((r["amount"] or 0) / 1e8),
            })
        return out

    # ---------------- URL / i18n ----------------
    def _url(self, locale: str, path: str) -> str:
        return f"{self.base_url}{self.base_path}{locale_prefix(locale)}{path}"

    def _ctx(self, locale: str, i18n: I18n, *, title: str, desc: str, path: str,
             trade_date: str, locales: tuple[str, ...]) -> dict:
        other = "en" if locale == DEFAULT else DEFAULT
        return {
            "lang": locale,
            "page_title": title,
            "description": desc,
            "canonical": self._url(locale, path),
            "hreflangs": [
                {"hreflang": loc, "href": self._url(loc, path)} for loc in locales
            ],
            "alt_url": f"{self.base_path}{locale_prefix(other)}{path}",
            "prefix": f"{self.base_path}{locale_prefix(locale)}",
            "base_path": self.base_path,
            "t": i18n.flat,
            "trade_date": trade_date,
        }

    # ---------------- 游资席位 ----------------
    def _people_rows(self, trade_date: str, i18n: I18n) -> list[dict]:
        aliases = _load_seat_aliases()
        rows = self.store.conn.execute(
            "SELECT r.operatedept_code code, s.seat_name name, "
            "SUM(CASE WHEN r.side='buy' THEN r.amount ELSE 0 END) buy, "
            "SUM(CASE WHEN r.side='sell' THEN r.amount ELSE 0 END) sell, "
            "COUNT(*) n FROM lhb_record r LEFT JOIN seat s USING(operatedept_code) "
            "WHERE r.trade_date=? GROUP BY r.operatedept_code, s.seat_name "
            "ORDER BY buy DESC",
            (trade_date,),
        ).fetchall()
        out = []
        for r in rows:
            buy = (r["buy"] or 0) / 1e8
            sell = (r["sell"] or 0) / 1e8
            net = buy - sell
            alias = aliases.get(str(r["code"]), "")
            full = r["name"] or r["code"]
            out.append({
                "code": r["code"],
                "name": alias or full,          # 列表页优先显示社区别名
                "full_name": full,
                "alias": alias,
                "buy_text": f"{buy:.2f}",
                "sell_text": f"{sell:.2f}",
                "net_text": f"{net:+.2f}",
                "net_cls": "up" if net > 0 else ("down" if net < 0 else "flat"),
                "records": r["n"],
            })
        return out

    def _person_stocks(self, code: str, trade_date: str) -> list[dict]:
        rows = self.store.conn.execute(
            "SELECT stock_code, "
            "SUM(CASE WHEN side='buy' THEN amount ELSE 0 END) buy, "
            "SUM(CASE WHEN side='sell' THEN amount ELSE 0 END) sell "
            "FROM lhb_record WHERE operatedept_code=? AND trade_date=? "
            "GROUP BY stock_code ORDER BY buy DESC LIMIT 30",
            (code, trade_date),
        ).fetchall()
        return [
            {"stock_code": r["stock_code"],
             "buy_text": f"{(r['buy'] or 0) / 1e8:.2f}",
             "sell_text": f"{(r['sell'] or 0) / 1e8:.2f}"}
            for r in rows
        ]

    # ---------------- 资金雷达 ----------------
    def _radar_data(self, trade_date: str) -> tuple[dict, list[dict]]:
        """返回 (按池分组的股票, 连板梯队分布)。"""
        rows = self.store.conn.execute(
            "SELECT stock_code, pool_type, ladder, amount, name, pct_chg, turnover, industry "
            "FROM limit_up WHERE trade_date=? ORDER BY COALESCE(amount, 0) DESC",
            (trade_date,),
        ).fetchall()
        pools: dict[str, list[dict]] = {"up": [], "break": [], "down": [], "strong": []}
        for r in rows:
            pct = r["pct_chg"]
            pools.setdefault(r["pool_type"], []).append({
                "code": r["stock_code"],
                "name": r["name"] or r["stock_code"],
                "pct_text": f"{pct:+.2f}%" if pct is not None else "-",
                "cls": _cls(r["pct_chg"]),
                "amount_text": f"{(r['amount'] or 0) / 1e8:.2f}",
                "turnover_text": f"{(r['turnover'] or 0):.2f}%",
                "ladder": r["ladder"],
                "industry": r["industry"] or "",
            })
        ladder = [
            {"ladder": r["ladder"], "n": r["n"]}
            for r in self.store.ladder_distribution(trade_date)
        ]
        return pools, ladder

    def _render(self, template: str, out_path: Path, ctx: dict) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.env.get_template(template).render(**ctx), encoding="utf-8")

    # ---------------- 构建 ----------------
    def build(self, trade_date: str, locales: tuple[str, ...] = SUPPORTED) -> dict:
        if self.out.exists():
            shutil.rmtree(self.out)
        (self.out / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy2(_ASSETS / "style.css", self.out / "assets" / "style.css")
        # GitHub Pages 需要 .nojekyll，否则下划线开头的文件被忽略
        (self.out / ".nojekyll").write_text("", encoding="utf-8")
        # 根目录重定向（项目站点入口）
        (self.out / "index.html").exists() or None

        pages = 0
        for loc in locales:
            pages += self._build_locale(loc, I18n(loc), trade_date, locales)
        return {"pages": pages, "out": str(self.out)}

    def _build_locale(self, locale: str, i18n: I18n, trade_date: str,
                      locales: tuple[str, ...]) -> int:
        base = self.out / (locale_prefix(locale).lstrip("/") or "")
        rows = self._rows(trade_date, i18n)
        n = 0

        # 首页
        self._render("index.html", base / "index.html", self._ctx(
            locale, i18n, title=i18n.t("index.title"), desc=i18n.t("index.lead"),
            path="/", trade_date=trade_date, locales=locales))
        n += 1

        # 列表页
        ctx = self._ctx(locale, i18n, title=i18n.t("sectors.title"),
                        desc=i18n.t("sectors.subtitle"), path="/sectors/",
                        trade_date=trade_date, locales=locales)
        ctx["sectors"] = rows
        self._render("sectors.html", base / "sectors" / "index.html", ctx)
        n += 1

        # 详情页
        for s in rows:
            dctx = self._ctx(locale, i18n, title=s["name"],
                             desc=f'{s["name"]} {s["ret1_text"]} / {s["ret5_text"]} / {s["ret20_text"]}',
                             path=f'/sectors/{s["code"]}/', trade_date=trade_date,
                             locales=locales)
            dctx["s"] = s
            self._render("sector.html", base / "sectors" / s["code"] / "index.html", dctx)
            n += 1

        # 游资席位
        prows = self._people_rows(trade_date, i18n)
        pctx = self._ctx(locale, i18n, title=i18n.t("people.title"),
                         desc=i18n.t("people.subtitle"), path="/people/",
                         trade_date=trade_date, locales=locales)
        pctx["seats"] = prows
        self._render("people.html", base / "people" / "index.html", pctx)
        n += 1

        for s in prows:
            dctx = self._ctx(locale, i18n, title=s["name"],
                             desc=f'{s["name"]} buy {s["buy_text"]} / sell {s["sell_text"]}',
                             path=f'/people/{s["code"]}/', trade_date=trade_date,
                             locales=locales)
            s["stocks"] = self._person_stocks(s["code"], trade_date)
            dctx["s"] = s
            self._render("person.html", base / "people" / s["code"] / "index.html", dctx)
            n += 1

        # 资金雷达
        pools, ladder = self._radar_data(trade_date)
        rctx = self._ctx(locale, i18n, title=i18n.t("radar.title"),
                         desc=i18n.t("radar.subtitle"), path="/radar/",
                         trade_date=trade_date, locales=locales)
        rctx["pools"] = pools
        rctx["ladder"] = ladder
        self._render("radar.html", base / "radar" / "index.html", rctx)
        n += 1
        return n
