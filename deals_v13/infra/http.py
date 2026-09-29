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


def _is_noon_catalog_api(url: str) -> bool:
    low = (url or "").lower()
    return (
        "/_vs/nc/mp-customer-catalog-api/" in low
        or "/_svc/catalog/" in low
    )


class StoreHttpClient:
    """One HTTP path for discovery and verification.

    V13 Milestone 3 adds a dedicated Noon catalog-API fast path using the
    Egypt locale. This avoids the rendered Noon storefront, which was returning
    403/timeouts from GitHub Actions.
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

    @staticmethod
    def _request_headers(url: str, store: str) -> dict[str, str]:
        if store == "noon" and _is_noon_catalog_api(url):
            # Noon's catalog service understands marketplace locale through
            # x-locale. Keep the browser-facing Accept-Language as a backup.
            return {
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
                "x-locale": "en-eg",
                "x-platform": "web",
                "x-mp": "noon",
                "Referer": "https://www.noon.com/egypt-en/",
                "Origin": "https://www.noon.com",
            }
        return {}

    async def _direct(self, url: str, extra_headers: dict[str, str] | None = None) -> FetchResult:
        started = time.monotonic()
        r = await self.client.get(url, headers=extra_headers or None)
        latency = int((time.monotonic() - started) * 1000)
        text = r.text or ""

        if r.status_code != 200:
            raise StoreHttpError(f"direct_http_{r.status_code}")
        if _is_protected(text):
            raise StoreHttpError("direct_protection")
        return FetchResult(
            url=url,
            text=text,
            status_code=r.status_code,
            via="direct",
            latency_ms=latency,
        )

    async def _proxy(self, url: str, extra_headers: dict[str, str] | None = None) -> FetchResult:
        endpoint = self._proxy_endpoint()
        if not endpoint or not self.settings.cloud_api_key:
            raise StoreHttpError("proxy_unavailable")

        started = time.monotonic()
        proxy_headers = {
            "x-api-key": self.settings.cloud_api_key,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        # If the Cloud proxy forwards request headers, this preserves the Noon
        # Egypt context; if it does not, direct API remains the preferred path.
        if extra_headers:
            for key in ("Accept", "Accept-Language", "x-locale", "x-platform", "x-mp"):
                if key in extra_headers:
                    proxy_headers[key] = extra_headers[key]

        r = await self.client.get(
            endpoint,
            params={"url": url},
            headers=proxy_headers,
            timeout=httpx.Timeout(35.0, connect=15.0),
        )
        latency = int((time.monotonic() - started) * 1000)
        text = r.text or ""

        if r.status_code != 200:
            raise StoreHttpError(f"proxy_http_{r.status_code}")
        if _is_protected(text):
            raise StoreHttpError("proxy_protection")
        return FetchResult(
            url=url,
            text=text,
            status_code=r.status_code,
            via="proxy",
            latency_ms=latency,
        )

    async def fetch(self, url: str, store: str, prefer_proxy: bool | None = None) -> FetchResult:
        host = urlparse(url).netloc.lower()
        if store == "amazon" and "amazon.eg" not in host:
            raise StoreHttpError("amazon_host_rejected")
        if store == "noon" and "noon.com" not in host:
            raise StoreHttpError("noon_host_rejected")

        extra_headers = self._request_headers(url, store)
        noon_api = store == "noon" and _is_noon_catalog_api(url)

        if prefer_proxy is None:
            prefer_proxy = (
                self.settings.noon_proxy_first if store == "noon"
                else self.settings.amazon_proxy_first
            )

        # Critical M3 behavior: the Noon JSON catalog API is substantially
        # lighter than the storefront and should be attempted directly first.
        if noon_api:
            prefer_proxy = False

        methods = (self._proxy, self._direct) if prefer_proxy else (self._direct, self._proxy)
        errors: list[str] = []
        sem = self._store_locks.get(store) or asyncio.Semaphore(2)

        async with sem:
            for round_no in range(2):
                for method in methods:
                    try:
                        return await method(url, extra_headers)
                    except (
                        StoreHttpError,
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        httpx.HTTPError,
                    ) as exc:
                        errors.append(f"{method.__name__}:{type(exc).__name__}:{exc}")
                if round_no == 0:
                    await asyncio.sleep(0.30 + random.random() * 0.45)

        raise StoreHttpError("fetch_failed | " + " | ".join(errors[-4:]))
