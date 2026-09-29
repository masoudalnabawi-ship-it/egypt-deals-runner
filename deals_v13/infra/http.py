\
from __future__ import annotations

import asyncio
import random
import time
from urllib.parse import urlparse

import httpx

from ..config import Settings
from ..models import FetchResult


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
}


class StoreHttpError(RuntimeError):
    pass


def _is_protected(text: str) -> bool:
    low = (text or "").lower()
    markers = (
        "robot check",
        "enter the characters you see below",
        "captcha",
        "sorry, we just need to make sure",
        "access denied",
        "unusual traffic",
    )
    return any(x in low for x in markers)


class StoreHttpClient:
    """One HTTP path for discovery and verification.

    Direct and Cloud Proxy are deliberately centralized so the verifier can never
    accidentally bypass the same fallback logic used by discovery.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(25.0, connect=12.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._store_locks = {
            "amazon": asyncio.Semaphore(4),
            "noon": asyncio.Semaphore(4),
        }

    async def aclose(self) -> None:
        await self.client.aclose()

    def _proxy_endpoint(self) -> str:
        base = self.settings.cloud_api_url.rstrip("/")
        if base.endswith("/api/deals"):
            base = base[: -len("/api/deals")]
        return base + "/api/store-proxy" if base else ""

    async def _direct(self, url: str) -> FetchResult:
        started = time.monotonic()
        r = await self.client.get(url)
        latency = int((time.monotonic() - started) * 1000)
        text = r.text or ""

        if r.status_code != 200:
            raise StoreHttpError(f"direct_http_{r.status_code}")
        if _is_protected(text):
            raise StoreHttpError("direct_protection")
        return FetchResult(url=url, text=text, status_code=r.status_code, via="direct", latency_ms=latency)

    async def _proxy(self, url: str) -> FetchResult:
        endpoint = self._proxy_endpoint()
        if not endpoint or not self.settings.cloud_api_key:
            raise StoreHttpError("proxy_unavailable")

        started = time.monotonic()
        r = await self.client.get(
            endpoint,
            params={"url": url},
            headers={
                "x-api-key": self.settings.cloud_api_key,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            },
            timeout=httpx.Timeout(35.0, connect=15.0),
        )
        latency = int((time.monotonic() - started) * 1000)
        text = r.text or ""

        if r.status_code != 200:
            raise StoreHttpError(f"proxy_http_{r.status_code}")
        if _is_protected(text):
            raise StoreHttpError("proxy_protection")
        return FetchResult(url=url, text=text, status_code=r.status_code, via="proxy", latency_ms=latency)

    async def fetch(self, url: str, store: str, prefer_proxy: bool | None = None) -> FetchResult:
        host = urlparse(url).netloc.lower()
        if store == "amazon" and "amazon.eg" not in host:
            raise StoreHttpError("amazon_host_rejected")
        if store == "noon" and "noon.com" not in host:
            raise StoreHttpError("noon_host_rejected")

        if prefer_proxy is None:
            prefer_proxy = (
                self.settings.noon_proxy_first if store == "noon"
                else self.settings.amazon_proxy_first
            )

        methods = (self._proxy, self._direct) if prefer_proxy else (self._direct, self._proxy)
        errors: list[str] = []
        sem = self._store_locks.get(store) or asyncio.Semaphore(2)

        async with sem:
            for round_no in range(2):
                for method in methods:
                    try:
                        return await method(url)
                    except (
                        StoreHttpError,
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        httpx.HTTPError,
                    ) as exc:
                        errors.append(f"{method.__name__}:{type(exc).__name__}:{exc}")
                if round_no == 0:
                    await asyncio.sleep(0.35 + random.random() * 0.55)

        raise StoreHttpError("fetch_failed | " + " | ".join(errors[-4:]))
