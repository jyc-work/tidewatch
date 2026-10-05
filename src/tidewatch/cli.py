"""tidewatch CLI。

用法：
    tidewatch run --stage sectors [--category industry|concept] [--date YYYY-MM-DD]
                 [--force] [--use-cache] [--codes BK0475,BK1296]
    tidewatch show --date YYYY-MM-DD
"""
from __future__ import annotations

import argparse
import sys

from .pipeline.sectors import resolve_target_date, run_sectors
from .render.builder import SiteBuilder
from .render.i18n import SUPPORTED
from .render.publish import count_pages, publish
from .store.db import Store
from .http import HttpClient
from .utils import ROOT, load_config, resolve


def _build(args) -> tuple[Store, HttpClient, dict]:
    cfg = load_config()
    paths = cfg.get("paths", {})
    fetch = cfg.get("fetch", {})
    store = Store(resolve(paths.get("db", "data/tidewatch.db")))
    store.init_schema()
    http = HttpClient(
        min_interval=fetch.get("min_interval", 1.0),
        jitter=fetch.get("jitter", 0.3),
        retries=fetch.get("retries", 4),
        timeout=fetch.get("timeout", 15),
        daily_max_requests=fetch.get("daily_max_requests", 600),
        raw_dir=resolve(paths.get("raw", "data/raw")),
        use_cache=getattr(args, "use_cache", False),
    )
    return store, http, cfg


def cmd_run(args) -> int:
    store, http, cfg = _build(args)

    if args.stage == "lhb":
        from .pipeline.lhb import run_lhb
        print(f"stage=lhb target={resolve_target_date(args.date)}")
        result = run_lhb(store, http, trade_date=args.date, force=args.force)
        store.close()
        print(f"status={result['status']} records={result['written']} seats={result['seats']}")
        return 0 if result["status"] in ("success", "skipped") else 1

    if args.stage == "radar":
        from .pipeline.radar import run_radar
        print(f"stage=radar target={resolve_target_date(args.date)}")
        result = run_radar(store, http, trade_date=args.date, force=args.force)
        store.close()
        print(f"status={result['status']} records={result['written']} by_pool={result['by_pool']}")
        return 0 if result["status"] in ("success", "skipped") else 1

    if args.stage == "stocks":
        from .pipeline.stocks import run_stocks
        print(f"stage=stocks target={resolve_target_date(args.date)}")
        result = run_stocks(store, http, trade_date=args.date, force=args.force)
        store.close()
        print(f"status={result['status']} records={result['written']}")
        return 0 if result["status"] in ("success", "skipped") else 1

    sample = cfg.get("sample", {})
    if args.all or args.top:
        # 从列表页发现板块（--top N 取前 N，概念已按资金净流入排序）
        from .datasource.ths import ThsSource
        secs = ThsSource(http).list_sectors(args.category)
        if args.top:
            secs = secs[: args.top]
        codes = [s.sector_code for s in secs]
        print(f"discovered {len(codes)} {args.category} sectors")
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.category == "concept":
        codes = sample.get("concepts", [])
    else:
        codes = sample.get("industries", [])
    if not codes:
        print("no sector codes given (use --codes / --all / --top)", file=sys.stderr)
        return 2
    print(f"stage=sectors category={args.category} codes={len(codes)} "
          f"target={resolve_target_date(args.date)}")
    result = run_sectors(
        store, http,
        sector_codes=codes, category=args.category,
        target_date=args.date, force=args.force,
    )
    store.close()
    print(f"status={result['status']} written={result['written']} "
          f"skipped={len(result['skipped'])}")
    if result["skipped"]:
        for c, why in result["skipped"][:10]:
            print(f"  skipped {c}: {why}")
    return 0 if result["status"] in ("success", "skipped") else 1


def cmd_show(args) -> int:
    store, http, cfg = _build(args)
    d = resolve_target_date(args.date)
    rows = store.conn.execute(
        "SELECT s.name, dd.sector_code, dd.close, dd.ret_1d, dd.ret_5d, dd.ret_20d, "
        "dd.stage, dd.amount, dd.source_provider FROM sector_daily dd "
        "JOIN sector s USING(sector_code) WHERE dd.trade_date=? ORDER BY dd.amount DESC",
        (d,),
    ).fetchall()
    print(f"trade_date={d}  count={len(rows)}")
    print(f"{'代码':<8}{'名称':<14}{'收盘':>10}{'1日':>9}{'5日':>9}{'20日':>9}  {'四段':<6}{'额(亿)':>9}  来源")
    for r in rows:
        def pct(x):
            return f"{x*100:.2f}%" if x is not None else "-"
        print(f"{r['sector_code']:<8}{r['name']:<14}{r['close']:>10.2f}"
              f"{pct(r['ret_1d']):>9}{pct(r['ret_5d']):>9}{pct(r['ret_20d']):>9}  "
              f"{r['stage'] or '-':<6}{(r['amount'] or 0)/1e8:>9.2f}  {r['source_provider']}")
    store.close()
    return 0


def cmd_render(args) -> int:
    store, http, cfg = _build(args)
    d = resolve_target_date(args.date)
    locales = SUPPORTED if args.lang == "all" else (args.lang,)
    out_new = resolve(args.out)
    builder = SiteBuilder(store, out_new, base_url=args.base_url,
                          base_path=args.base_path, top_stocks=args.top_stocks)
    res = builder.build(d, locales)
    print(f"built {res['pages']} pages -> {res['out']} (locales={','.join(locales)})")

    if args.publish:
        ok, msg = publish(out_new, resolve("dist"), min_pages=args.min_pages)
        store.record_publish(d, res["pages"], "", "render-v1",
                             "published" if ok else "rejected", msg)
        print(("published: " if ok else "REFUSED: ") + msg)
        store.close()
        return 0 if ok else 1

    store.close()
    return 0


def cmd_pages(args) -> int:
    d = resolve(args.dir)
    print(f"{d}: {count_pages(d)} html pages")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tidewatch", description="A 股市场图谱（观潮）")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="执行数据管道")
    r.add_argument("--stage", default="sectors",
                   choices=["sectors", "lhb", "radar", "stocks"])
    r.add_argument("--category", default="industry", choices=["industry", "concept"])
    r.add_argument("--date", help="目标交易日 YYYY-MM-DD（默认最近已收盘交易日）")
    r.add_argument("--codes", help="逗号分隔的板块代码，覆盖 config.sample")
    r.add_argument("--all", action="store_true", help="从列表页发现全部板块并抓取")
    r.add_argument("--top", type=int, help="仅抓前 N 个（概念按资金净流入排序）")
    r.add_argument("--force", action="store_true", help="忽略幂等检查强制重跑")
    r.add_argument("--use-cache", action="store_true", help="优先读 data/raw 缓存（离线）")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("show", help="查看已落库的板块数据")
    s.add_argument("--date", help="交易日 YYYY-MM-DD")
    s.set_defaults(func=cmd_show)

    b = sub.add_parser("render", help="构建静态站（中英双语）")
    b.add_argument("--date", help="交易日 YYYY-MM-DD")
    b.add_argument("--lang", default="all", choices=["all", *SUPPORTED])
    b.add_argument("--out", default="dist.new", help="输出目录（默认 dist.new）")
    b.add_argument("--base-url", default="https://localhost", help="canonical/hreflang 用的基 URL")
    b.add_argument("--base-path", default="", help="子路径前缀（GitHub Pages 项目站点用 /<repo>）")
    b.add_argument("--publish", action="store_true", help="构建后原子发布到 dist/")
    b.add_argument("--min-pages", type=int, default=6, help="发布守门的页面数下限")
    b.add_argument("--top-stocks", type=int, default=300,
                   help="生成个股详情页的数量（按成交额 Top N）")
    b.set_defaults(func=cmd_render)

    g = sub.add_parser("pages", help="统计目录下的 html 页面数")
    g.add_argument("--dir", default="dist")
    g.set_defaults(func=cmd_pages)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
