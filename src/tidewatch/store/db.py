"""SQLite 存储层：schema / 运行账本 / 幂等判据。

对应 DESIGN §6.2（全表溯源）与 §6.3（运行账本与原子写入）。
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..utils import now_beijing

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sector (
  sector_code TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  name_en     TEXT,
  category    TEXT NOT NULL,          -- industry | concept
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_daily (
  sector_code        TEXT NOT NULL,
  trade_date         TEXT NOT NULL,
  close              REAL,
  ret_1d             REAL,
  ret_5d             REAL,
  ret_20d            REAL,
  stage              TEXT,
  amount             REAL,
  source_provider    TEXT NOT NULL,
  source_symbol      TEXT,
  calculation_method TEXT NOT NULL,
  member_snapshot_id INTEGER,
  available_at       TEXT NOT NULL,
  input_hash         TEXT NOT NULL,
  algorithm_version  TEXT NOT NULL,
  PRIMARY KEY (sector_code, trade_date)
);

CREATE TABLE IF NOT EXISTS sector_member_snapshot (
  snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  sector_code     TEXT NOT NULL,
  trade_date      TEXT NOT NULL,
  source_provider TEXT NOT NULL,
  input_hash      TEXT NOT NULL,
  UNIQUE (sector_code, trade_date, source_provider)
);

CREATE TABLE IF NOT EXISTS sector_member (
  snapshot_id INTEGER NOT NULL,
  stock_code  TEXT NOT NULL,
  PRIMARY KEY (snapshot_id, stock_code)
);

CREATE TABLE IF NOT EXISTS stock_daily (
  stock_code        TEXT NOT NULL,
  trade_date        TEXT NOT NULL,
  name              TEXT,
  close             REAL,
  pct_chg           REAL,
  turnover          REAL,
  amount            REAL,
  pe_ttm            REAL,
  pb                REAL,
  total_mcap        REAL,
  float_mcap        REAL,
  source_provider   TEXT NOT NULL,
  available_at      TEXT NOT NULL,
  input_hash        TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  PRIMARY KEY (stock_code, trade_date)
);

CREATE TABLE IF NOT EXISTS lhb_record (
  trade_date        TEXT NOT NULL,
  stock_code        TEXT NOT NULL,
  operatedept_code  TEXT NOT NULL,
  side              TEXT NOT NULL,
  amount            REAL,
  reason            TEXT,
  source_provider   TEXT NOT NULL,
  input_hash        TEXT NOT NULL,
  PRIMARY KEY (trade_date, stock_code, operatedept_code, side)
);

CREATE TABLE IF NOT EXISTS seat (
  operatedept_code      TEXT PRIMARY KEY,
  seat_name             TEXT NOT NULL,
  last_seen_name        TEXT,
  activity_evidence     TEXT,
  identity_evidence     TEXT,
  classification        TEXT,
  classification_method TEXT,
  classifier_version    TEXT,
  confidence            TEXT,
  source_query          TEXT,
  raw_hash              TEXT,
  updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS limit_up (
  trade_date   TEXT NOT NULL,
  stock_code   TEXT NOT NULL,
  pool_type    TEXT NOT NULL,
  name         TEXT,
  pct_chg      REAL,
  turnover     REAL,
  industry     TEXT,
  ladder       INTEGER,
  amount       REAL,
  source_provider TEXT NOT NULL,
  input_hash   TEXT NOT NULL,
  PRIMARY KEY (trade_date, stock_code, pool_type)
);

CREATE TABLE IF NOT EXISTS run_ledger (
  run_id            TEXT PRIMARY KEY,
  task              TEXT NOT NULL,
  trade_date        TEXT,
  provider          TEXT,
  domain            TEXT,
  endpoint          TEXT,
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  status            TEXT NOT NULL,     -- running | success | failed | rejected
  row_count         INTEGER,
  raw_hash          TEXT,
  schema_version    TEXT,
  algorithm_version TEXT,
  error_class       TEXT,
  error_message     TEXT
);

CREATE TABLE IF NOT EXISTS publish (
  publish_id        TEXT PRIMARY KEY,
  trade_date        TEXT NOT NULL,
  built_at          TEXT NOT NULL,
  page_count        INTEGER,
  data_hash         TEXT,
  algorithm_version TEXT,
  status            TEXT,              -- published | rejected
  reason            TEXT
);

CREATE INDEX IF NOT EXISTS idx_sector_daily_date ON sector_daily (trade_date);
CREATE INDEX IF NOT EXISTS idx_run_ledger_task ON run_ledger (task, trade_date, status);
"""


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        # 轻量 migration：为已存在的 limit_up 补列（旧库升级用）
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(limit_up)")}
        for col, typ in (("name", "TEXT"), ("pct_chg", "REAL"),
                         ("turnover", "REAL"), ("industry", "TEXT")):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE limit_up ADD COLUMN {col} {typ}")
        # stock_daily 同样补列
        scols = {r["name"] for r in self.conn.execute("PRAGMA table_info(stock_daily)")}
        for col, typ in (("name", "TEXT"), ("pe_ttm", "REAL"), ("pb", "REAL"),
                         ("total_mcap", "REAL"), ("float_mcap", "REAL")):
            if col not in scols:
                self.conn.execute(f"ALTER TABLE stock_daily ADD COLUMN {col} {typ}")
        self.conn.commit()

    # ---------------- 运行账本 ----------------
    def begin_run(
        self, task: str, *, trade_date: str | None = None, provider: str | None = None,
        algorithm_version: str = "v0",
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO run_ledger (run_id, task, trade_date, provider, started_at, "
            "status, algorithm_version) VALUES (?,?,?,?,?,?,?)",
            (run_id, task, trade_date, provider, now_beijing().isoformat(), "running",
             algorithm_version),
        )
        self.conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        domain: str | None = None,
        endpoint: str | None = None,
        row_count: int | None = None,
        raw_hash: str | None = None,
        schema_version: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE run_ledger SET finished_at=?, status=?, domain=?, endpoint=?, "
            "row_count=?, raw_hash=?, schema_version=?, error_class=?, error_message=? "
            "WHERE run_id=?",
            (now_beijing().isoformat(), status, domain, endpoint, row_count, raw_hash,
             schema_version, error_class, error_message, run_id),
        )
        self.conn.commit()

    def is_done(
        self, task: str, trade_date: str, algorithm_version: str,
        expected_count: int | None = None,
    ) -> bool:
        """幂等判据（DESIGN §6.3）：当日成功 + 算法版本一致 + 行数不少于预期。

        `expected_count` 用于避免「先跑 3 个板块、后要跑 90 个」被误判为已完成。
        """
        row = self.conn.execute(
            "SELECT row_count FROM run_ledger WHERE task=? AND trade_date=? "
            "AND status='success' AND algorithm_version=? "
            "ORDER BY finished_at DESC LIMIT 1",
            (task, trade_date, algorithm_version),
        ).fetchone()
        if row is None:
            return False
        if expected_count is not None and (row["row_count"] or 0) < expected_count:
            return False
        return True

    # ---------------- 板块 ----------------
    def upsert_sector(
        self, sector_code: str, name: str, category: str, name_en: str | None = None
    ) -> None:
        self.conn.execute(
            "INSERT INTO sector (sector_code, name, name_en, category, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(sector_code) DO UPDATE SET "
            "name=excluded.name, name_en=COALESCE(excluded.name_en, sector.name_en), "
            "category=excluded.category, updated_at=excluded.updated_at",
            (sector_code, name, name_en, category, now_beijing().isoformat()),
        )

    def upsert_sector_daily(self, rec: dict[str, Any]) -> None:
        cols = [
            "sector_code", "trade_date", "close", "ret_1d", "ret_5d", "ret_20d",
            "stage", "amount", "source_provider", "source_symbol",
            "calculation_method", "member_snapshot_id", "available_at",
            "input_hash", "algorithm_version",
        ]
        placeholders = ",".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT OR REPLACE INTO sector_daily ({','.join(cols)}) VALUES ({placeholders})",
            tuple(rec.get(c) for c in cols),
        )

    def get_sector_daily(self, sector_code: str, trade_date: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sector_daily WHERE sector_code=? AND trade_date=?",
            (sector_code, trade_date),
        ).fetchone()

    def count_sector_daily(self, trade_date: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM sector_daily WHERE trade_date=?", (trade_date,)
        ).fetchone()["c"]

    def record_publish(
        self, trade_date: str, page_count: int, data_hash: str,
        algorithm_version: str, status: str, reason: str | None = None,
    ) -> str:
        pid = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO publish (publish_id, trade_date, built_at, page_count, data_hash, "
            "algorithm_version, status, reason) VALUES (?,?,?,?,?,?,?,?)",
            (pid, trade_date, now_beijing().isoformat(), page_count, data_hash,
             algorithm_version, status, reason),
        )
        self.conn.commit()
        return pid

    # ---------------- 龙虎榜 / 席位 ----------------
    def upsert_lhb_record(
        self, *, trade_date: str, stock_code: str, operatedept_code: str, side: str,
        amount: float, reason: str, source_provider: str, input_hash: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO lhb_record (trade_date, stock_code, operatedept_code, "
            "side, amount, reason, source_provider, input_hash) VALUES (?,?,?,?,?,?,?,?)",
            (trade_date, stock_code, operatedept_code, side, amount, reason,
             source_provider, input_hash),
        )

    def upsert_seat(
        self, *, operatedept_code: str, seat_name: str, classification: str | None = None,
        classification_method: str | None = None, confidence: str | None = None,
        activity_evidence: str = "measured", identity_evidence: str = "unknown",
        source_query: str | None = None,
    ) -> None:
        """席位表：名称会变，主键用代码；已存在时不覆盖人工分类。"""
        self.conn.execute(
            "INSERT INTO seat (operatedept_code, seat_name, last_seen_name, "
            "activity_evidence, identity_evidence, classification, classification_method, "
            "confidence, source_query, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(operatedept_code) DO UPDATE SET "
            "seat_name=excluded.seat_name, last_seen_name=excluded.last_seen_name, "
            "activity_evidence=excluded.activity_evidence, "
            "classification=COALESCE(seat.classification, excluded.classification), "
            "classification_method=COALESCE(seat.classification_method, excluded.classification_method), "
            "confidence=COALESCE(seat.confidence, excluded.confidence), "
            "updated_at=excluded.updated_at",
            (operatedept_code, seat_name, seat_name, activity_evidence, identity_evidence,
             classification, classification_method, confidence, source_query,
             now_beijing().isoformat()),
        )

    def lhb_seat_summary(self, trade_date: str) -> list:
        """当日席位买卖汇总（用于游资页）。"""
        return self.conn.execute(
            "SELECT r.operatedept_code, s.seat_name, "
            "SUM(CASE WHEN r.side='buy' THEN r.amount ELSE 0 END) buy_amt, "
            "SUM(CASE WHEN r.side='sell' THEN r.amount ELSE 0 END) sell_amt, "
            "COUNT(*) records "
            "FROM lhb_record r LEFT JOIN seat s USING(operatedept_code) "
            "WHERE r.trade_date=? GROUP BY r.operatedept_code, s.seat_name "
            "ORDER BY buy_amt DESC",
            (trade_date,),
        ).fetchall()

    def count_lhb(self, trade_date: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM lhb_record WHERE trade_date=?", (trade_date,)
        ).fetchone()["c"]

    def upsert_stock_daily(self, rec: dict) -> None:
        cols = ["stock_code", "trade_date", "name", "close", "pct_chg", "turnover",
                "amount", "pe_ttm", "pb", "total_mcap", "float_mcap",
                "source_provider", "available_at", "input_hash", "algorithm_version"]
        ph = ",".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT OR REPLACE INTO stock_daily ({','.join(cols)}) VALUES ({ph})",
            tuple(rec.get(c) for c in cols),
        )

    def count_stock_daily(self, trade_date: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM stock_daily WHERE trade_date=?", (trade_date,)
        ).fetchone()["c"]

    def top_stocks(self, trade_date: str, limit: int = 300) -> list:
        """按成交额排序取头部股票（个股列表页）。"""
        return self.conn.execute(
            "SELECT * FROM stock_daily WHERE trade_date=? "
            "ORDER BY COALESCE(amount, 0) DESC LIMIT ?",
            (trade_date, limit),
        ).fetchall()

    def get_stock(self, code: str, trade_date: str):
        return self.conn.execute(
            "SELECT * FROM stock_daily WHERE stock_code=? AND trade_date=?",
            (code, trade_date),
        ).fetchone()

    # ---------------- 涨跌停池 ----------------
    def upsert_limit_up(
        self, *, trade_date: str, stock_code: str, pool_type: str,
        name: str, pct_chg: float, turnover: float, industry: str,
        ladder: int, amount: float, source_provider: str, input_hash: str,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO limit_up (trade_date, stock_code, pool_type, name, "
            "pct_chg, turnover, industry, ladder, amount, source_provider, input_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (trade_date, stock_code, pool_type, name, pct_chg, turnover, industry,
             ladder, amount, source_provider, input_hash),
        )

    def count_limit_up(self, trade_date: str, pool_type: str | None = None) -> int:
        if pool_type:
            return self.conn.execute(
                "SELECT COUNT(*) c FROM limit_up WHERE trade_date=? AND pool_type=?",
                (trade_date, pool_type),
            ).fetchone()["c"]
        return self.conn.execute(
            "SELECT COUNT(*) c FROM limit_up WHERE trade_date=?", (trade_date,)
        ).fetchone()["c"]

    def ladder_distribution(self, trade_date: str) -> list:
        """连板梯队：涨停池按连板数分组。"""
        return self.conn.execute(
            "SELECT ladder, COUNT(*) n FROM limit_up WHERE trade_date=? AND pool_type='up' "
            "GROUP BY ladder ORDER BY ladder DESC",
            (trade_date,),
        ).fetchall()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """原子写入：异常回滚。"""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        self.conn.close()
