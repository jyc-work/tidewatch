"""国际化：文案字典 + 板块译名。

URL 约定（DESIGN §7.4）：中文在根 `/`，英文在 `/en/`。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_LOCALES_DIR = _HERE / "locales"
_NAMES_EN = _HERE.parents[2] / "mapping" / "sector_names_en.yaml"

SUPPORTED = ("zh-CN", "en")
DEFAULT = "zh-CN"


def locale_prefix(locale: str) -> str:
    """URL 前缀：默认语言为空，其余用短码（/en）。"""
    if locale == DEFAULT:
        return ""
    return "/" + locale.split("-")[0]


class I18n:
    def __init__(self, locale: str = DEFAULT) -> None:
        if locale not in SUPPORTED:
            raise ValueError(f"unsupported locale: {locale}")
        self.locale = locale
        self.d: dict = yaml.safe_load(
            (_LOCALES_DIR / f"{locale}.yaml").read_text(encoding="utf-8")
        ) or {}
        self._en: dict = {}
        if _NAMES_EN.exists():
            self._en = yaml.safe_load(_NAMES_EN.read_text(encoding="utf-8")) or {}

    def t(self, path: str, **kw) -> str:
        cur: object = self.d
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return path
            cur = cur[key]
        if not isinstance(cur, str):
            return path
        return cur.format(**kw) if kw else cur

    def stage(self, zh_label: str | None) -> str:
        if not zh_label:
            return "-"
        m = self.d.get("stage", {})
        return m.get(zh_label, zh_label)

    def sector_name(self, code: str, zh_name: str) -> str:
        """英文页优先用译名表，缺失则回退中文（不臆造）。"""
        if self.locale == DEFAULT:
            return zh_name
        return (self._en.get(code) or {}).get("en") or zh_name

    @property
    def flat(self) -> dict[str, str]:
        """展平嵌套字典，供模板用 t["site.name"] 形式访问。"""
        def walk(d: dict, prefix: str = "") -> dict[str, str]:
            out: dict[str, str] = {}
            for k, v in d.items():
                key = f"{prefix}{k}"
                if isinstance(v, dict):
                    out.update(walk(v, f"{key}."))
                else:
                    out[key] = v
            return out

        return walk(self.d)

    @property
    def prefix(self) -> str:
        return locale_prefix(self.locale)
