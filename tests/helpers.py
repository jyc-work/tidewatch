"""测试公共工具：离线 FakeHttp，让全链路可离线跑（§10.1 验收项 #8）。"""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeFetched:
    def __init__(self, text: str, host: str = "d.10jqka.com.cn") -> None:
        self.url = "fake"
        self.host = host
        self.status = 200
        self.text = text
        self.attempts = 1
        self.from_cache = False

    def json(self) -> dict:
        import json

        return json.loads(self.text)


class FakeHttp:
    """按 path 子串匹配 fixture 文件。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        # mapping: path 子串 -> fixture 文件名
        self.mapping = mapping
        self.calls: list[str] = []

    def get_with_fallback(self, hosts, path, **kw) -> FakeFetched:
        self.calls.append(path)
        for key, fname in self.mapping.items():
            if key in path:
                text = (FIXTURES / fname).read_text(encoding="utf-8")
                return FakeFetched(text)
        raise KeyError(f"no fixture for path: {path}")


def kline_fake() -> FakeHttp:
    return FakeHttp(
        {
            "bk_881101": "ths/kline_881101.js",
            "bk_881121": "ths/kline_881121.js",
            "bk_881273": "ths/kline_881273.js",
        }
    )
