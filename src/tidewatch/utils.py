"""通用工具：日志 / 时区 / 配置加载。

从 daily-review/utils.py 迁移，去掉 .env 依赖（本项目当前无需任何 key）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

TZ = ZoneInfo("Asia/Shanghai")
# src/tidewatch/utils.py -> 项目根
ROOT = Path(__file__).resolve().parents[2]


def now_beijing() -> datetime:
    return datetime.now(TZ)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def load_config(path: str | Path | None = None) -> dict:
    """加载 config/config.yaml。"""
    p = Path(path) if path else ROOT / "config" / "config.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data or {}


def resolve(rel: str | Path) -> Path:
    """把配置里的相对路径解析为项目根下的绝对路径。"""
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p
