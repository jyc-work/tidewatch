"""统一 HTTP 层：按域名限速 + 抖动 + 指数退避 + 多域名轮换 + 请求计数 + 原始留档。

为什么需要这个层（实测教训，DESIGN §4.7）：
    探索期连续请求东财导致 IP 被临时封禁（`RemoteDisconnected`，持续数十分钟）。
    因此限速不是优化项，而是 P0 的纪律。

设计要点：
    - 按 host 串行限速，最小间隔 + 随机抖动（避免固定节奏被识别）
    - 多域名轮换：调用方给候选 host 列表，逐个尝试（实测同接口不同域名可用性不一致）
    - 每次响应落 data/raw/{hash}.json，开发期可 `use_cache=True` 离线复用
    - `Fetched` 携带实际命中 host，供 run_ledger 记录（DESIGN §6.3）
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from .utils import get_logger

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

log = get_logger("http")


class FetchError(Exception):
    """重试耗尽或不可重试的错误。"""


class RateLimiter:
    """按 host 限速：串行 + 最小间隔 + 随机抖动。"""

    def __init__(self, min_interval: float = 1.0, jitter: float = 0.3) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            prev = self._last.get(host, 0.0)
            gap = self.min_interval + random.uniform(0, self.jitter)
            sleep = prev + gap - now
            if sleep > 0:
                time.sleep(sleep)
            self._last[host] = time.monotonic()


@dataclass
class Fetched:
    """一次成功的抓取结果，带溯源信息。"""

    url: str
    host: str
    status: int
    text: str
    attempts: int
    from_cache: bool = False

    def json(self) -> dict:
        return json.loads(self.text)


class HttpClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        jitter: float = 0.3,
        retries: int = 4,
        timeout: float = 15.0,
        daily_max_requests: int = 600,
        raw_dir: str | Path | None = None,
        use_cache: bool = False,
        trust_env: bool = False,
    ) -> None:
        self.retries = retries
        self.timeout = timeout
        self.daily_max_requests = daily_max_requests
        self.raw_dir = Path(raw_dir) if raw_dir else None
        self.use_cache = use_cache
        self.limiter = RateLimiter(min_interval, jitter)
        self.request_count = 0
        self._lock = threading.Lock()
        self._session = requests.Session()
        # 数据源（同花顺/东财/腾讯）均为国内直连，默认忽略系统代理环境变量；
        # 系统代理配置错误时会导致 ProxyError（Windows 本地实测踩到）。
        self._session.trust_env = trust_env
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ---------------- 内部 ----------------
    def _cache_path(self, url: str) -> Path | None:
        if self.raw_dir is None:
            return None
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.raw_dir / f"{h}.json"

    def _write_cache(self, url: str, text: str, host: str, status: int) -> str:
        """落原始响应，返回 raw_hash。"""
        raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        p = self._cache_path(url)
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {"url": url, "host": host, "status": status, "raw_hash": raw_hash, "text": text},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return raw_hash

    def _read_cache(self, url: str) -> tuple[str, str, int, str] | None:
        p = self._cache_path(url)
        if p is None or not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d["text"], d["host"], d["status"], d.get("raw_hash", "")
        except Exception:
            return None

    def _one(self, url: str, host: str, headers: dict | None) -> Fetched:
        h = {"User-Agent": random.choice(UA_POOL)}
        if headers:
            h.update(headers)
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.limiter.wait(host)
            with self._lock:
                if self.request_count >= self.daily_max_requests:
                    raise FetchError(
                        f"daily request limit exceeded ({self.daily_max_requests})"
                    )
                self.request_count += 1
            try:
                resp = self._session.get(url, headers=h, timeout=self.timeout)
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_err = FetchError(f"HTTP {resp.status_code}: {url}")
                    # 5xx（如个别板块无数据返回 502）不做长重试，避免拖垮整批
                    if attempt < min(self.retries, 2):
                        time.sleep(min(2 ** (attempt - 1), 8))
                        continue
                    raise last_err
                resp.encoding = resp.apparent_encoding or "utf-8"
                return Fetched(url, host, resp.status_code, resp.text, attempt)
            except requests.RequestException as e:
                last_err = e
                # 指数退避 1 -> 2 -> 4 -> 8
                time.sleep(min(2 ** (attempt - 1), 8))
        raise FetchError(f"{host} failed after {self.retries} attempts: {last_err}")

    # ---------------- 公开 ----------------
    def get_with_fallback(
        self,
        hosts: list[str],
        path: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> Fetched:
        """在候选 host 间轮换，第一个成功即返回。记录实际命中 host。"""
        qs = ""
        if params:
            from urllib.parse import urlencode

            qs = "?" + urlencode(params)
        errors: list[str] = []
        for host in hosts:
            url = f"https://{host}{path}{qs}"
            if self.use_cache:
                cached = self._read_cache(url)
                if cached is not None:
                    text, chost, status, _ = cached
                    log.info("cache hit: %s", url)
                    return Fetched(url, chost, status, text, 0, from_cache=True)
            try:
                f = self._one(url, host, headers)
                f_hash = self._write_cache(url, f.text, host, f.status)
                log.info("fetched %s (%d bytes, host=%s, attempts=%d, hash=%s)",
                         url, len(f.text), host, f.attempts, f_hash[:8])
                return f
            except FetchError as e:
                errors.append(f"{host}: {e}")
                log.warning("host failed, trying next: %s", host)
        raise FetchError("all hosts failed:\n  " + "\n  ".join(errors))

    def get_json(self, hosts: list[str], path: str, **kw) -> dict:
        return self.get_with_fallback(hosts, path, **kw).json()
