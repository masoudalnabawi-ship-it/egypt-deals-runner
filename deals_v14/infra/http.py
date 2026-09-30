from __future__ import annotations

import asyncio
import os
import random
import re
import time
from urllib.parse import parse_qs, quote_plus, urlparse

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


def _noon_storefront_url(url: str) -> str:
    """Translate internal Noon catalog search URLs to Egypt storefront URLs.

    Product-page URLs are already user-facing and are returned unchanged.
    """
    raw = str(url or "").strip()
    p = urlparse(raw)
    if "/_vs/nc/mp-customer-catalog-api/" in p.path:
        q = parse_qs(p.query).get("q", [""])[0]
        if q:
            return "https://www.noon.com/egypt-en/search/?q=" + quote_plus(q)
    return raw


class StoreHttpClient:
    """Central V13 transport for Amazon and Noon.

    Noon transport ladder:
      direct JSON/storefront -> cloud proxy -> rendered Egypt storefront browser.

    The browser fallback is public-page rendering only. It does not solve or
    defeat CAPTCHAs; protected responses are rejected.
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
        self._browser_lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._browser_context = None
        self._noon_cffi_session = None
        self._noon_cffi_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self.client.aclose()

        if self._noon_cffi_session is not None:
            try:
                self._noon_cffi_session.close()
            except Exception:
                pass
            self._noon_cffi_session = None
        if self._browser_context is not None:
            try:
                await self._browser_context.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass

    def _proxy_endpoint(self) -> str:
        base = self.settings.cloud_api_url.rstrip("/")
        if base.endswith("/api/deals"):
            base = base[: -len("/api/deals")]
        return base + "/api/store-proxy" if base else ""

    @staticmethod
    def _request_headers(url: str, store: str) -> dict[str, str]:
        if store == "noon" and _is_noon_catalog_api(url):
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

    def _noon_cffi_sync(self, url: str) -> FetchResult:
        from curl_cffi import requests as cffi_requests

        started = time.monotonic()

        if self._noon_cffi_session is None:
            self._noon_cffi_session = cffi_requests.Session(
                impersonate="chrome"
            )

        api_target = _is_noon_catalog_api(url)

        headers = {
            "accept-language": "en-EG,en;q=0.9,ar-EG;q=0.8",
            "referer": "https://www.noon.com/egypt-en/",
        }

        if api_target:
            headers.update({
                "accept": "application/json, text/plain, */*",
                "x-locale": "en-eg",
                "x-platform": "web",
                "x-mp": "noon",
                "x-mp-country": "eg",
                "x-country-code": "eg",
                "origin": "https://www.noon.com",
            })
        else:
            headers["accept"] = (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            )

        r = self._noon_cffi_session.get(
            url,
            headers=headers,
            timeout=18,
            allow_redirects=True,
        )

        latency = int(
            (time.monotonic() - started) * 1000
        )
        text = r.text or ""

        if r.status_code != 200:
            raise StoreHttpError(
                f"noon_cffi_http_{r.status_code}"
            )

        if _is_protected(text):
            raise StoreHttpError(
                "noon_cffi_protection"
            )

        if not api_target and len(text) < 800:
            raise StoreHttpError(
                "noon_cffi_empty_storefront"
            )

        if not api_target:
            low_text = text.lower()
            has_product_evidence = bool(
                re.search(
                    r"/[a-z0-9]{8,24}/p/?",
                    low_text,
                    re.I,
                )
                or '"sku"' in low_text
                or '"catalog_sku"' in low_text
                or "productcard" in low_text
                or "product-box" in low_text
            )
            if not has_product_evidence:
                raise StoreHttpError(
                    "noon_cffi_unrendered_storefront"
                )

        return FetchResult(
            url=str(r.url or url),
            text=text,
            status_code=r.status_code,
            via="noon_cffi",
            latency_ms=latency,
        )

    async def _noon_cffi(self, url: str) -> FetchResult:
        async with self._noon_cffi_lock:
            return await asyncio.to_thread(
                self._noon_cffi_sync,
                url,
            )

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

    async def _ensure_browser(self):
        if self._browser_context is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise StoreHttpError(f"browser_unavailable:{type(exc).__name__}") from exc

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-http2",
                "--disable-quic",
            ],
        )
        self._browser_context = await self._browser.new_context(
            locale="en-EG",
            timezone_id="Africa/Cairo",
            user_agent=DEFAULT_HEADERS["User-Agent"],
            viewport={"width": 1440, "height": 1100},
            extra_http_headers={
                "Accept-Language": "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
            },
        )

    async def _browser_noon(self, url: str) -> FetchResult:
        if os.getenv("V13_NOON_BROWSER_FALLBACK", "1").strip().lower() not in {
            "1", "true", "yes", "on"
        }:
            raise StoreHttpError("browser_fallback_disabled")

        target = _noon_storefront_url(url) if _is_noon_catalog_api(url) else url
        started = time.monotonic()

        async with self._browser_lock:
            await self._ensure_browser()
            page = await self._browser_context.new_page()
            try:
                api_target = _is_noon_catalog_api(target)
                if api_target:
                    headers = self._request_headers(target, "noon")
                    if headers:
                        await page.set_extra_http_headers(headers)
                else:
                    # Storefront warm-up is only useful for actual HTML pages.
                    try:
                        await page.goto(
                            "https://www.noon.com/egypt-en/",
                            wait_until="domcontentloaded",
                            timeout=12000,
                        )
                        await page.wait_for_timeout(350)
                    except Exception:
                        pass

                response = await page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=22000 if api_target else 35000,
                )
                await page.wait_for_timeout(
                    500 if api_target else 1800
                )

                if not api_target:
                    try:
                        await page.wait_for_selector(
                            "a[href*='/p/']",
                            timeout=9000,
                        )
                    except Exception:
                        pass

                    # Trigger lazy product grids.
                    try:
                        await page.evaluate(
                            "window.scrollTo(0, "
                            "Math.min(document.body.scrollHeight, 1800))"
                        )
                        await page.wait_for_timeout(900)
                        await page.evaluate(
                            "window.scrollTo(0, 0)"
                        )
                    except Exception:
                        pass

                if api_target:
                    text = await page.locator("body").inner_text(timeout=5000)
                else:
                    text = await page.content()
                status = response.status if response is not None else 200

                if status >= 400:
                    raise StoreHttpError(f"browser_http_{status}")
                if _is_protected(text):
                    raise StoreHttpError("browser_protection")
                if len(text) < 1000:
                    raise StoreHttpError("browser_empty_page")

                latency = int((time.monotonic() - started) * 1000)
                return FetchResult(
                    url=target,
                    text=text,
                    status_code=status,
                    via="browser",
                    latency_ms=latency,
                )
            finally:
                await page.close()

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
        if noon_api:
            prefer_proxy = False

        methods = (self._proxy, self._direct) if prefer_proxy else (self._direct, self._proxy)
        errors: list[str] = []
        sem = self._store_locks.get(store) or asyncio.Semaphore(2)

        async with sem:
            if store == "noon":
                # 1) Independent Chrome TLS transport first.
                try:
                    return await self._noon_cffi(url)
                except Exception as exc:
                    errors.append(
                        f"_noon_cffi:{type(exc).__name__}:{exc}"
                    )

                # 2) For search/catalog API URLs, render the corresponding
                # public Egypt storefront instead of repeatedly hitting
                # the blocked internal endpoint.
                if noon_api:
                    mapped = _noon_storefront_url(url)

                    if mapped != url:
                        try:
                            return await self._browser_noon(url)
                        except Exception as exc:
                            errors.append(
                                f"_browser_noon:"
                                f"{type(exc).__name__}:{exc}"
                            )

                    # Product-detail APIs have no q= search mapping.
                    # Fail fast so verifier immediately tries the public
                    # Noon product page.
                    raise StoreHttpError(
                        "fetch_failed | "
                        + " | ".join(errors[-8:])
                    )

                # 3) Public Noon Egypt storefront through real Chromium.
                try:
                    return await self._browser_noon(url)
                except Exception as exc:
                    errors.append(
                        f"_browser_noon:"
                        f"{type(exc).__name__}:{exc}"
                    )

                # 4) Last-resort network transports.
                for method in methods:
                    try:
                        return await method(
                            url,
                            extra_headers,
                        )
                    except (
                        StoreHttpError,
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        httpx.HTTPError,
                    ) as exc:
                        errors.append(
                            f"{method.__name__}:"
                            f"{type(exc).__name__}:{exc}"
                        )

                raise StoreHttpError(
                    "fetch_failed | "
                    + " | ".join(errors[-8:])
                )

            # Amazon transport stays exactly as before.
            for round_no in range(2):
                for method in methods:
                    try:
                        return await method(
                            url,
                            extra_headers,
                        )
                    except (
                        StoreHttpError,
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        httpx.HTTPError,
                    ) as exc:
                        errors.append(
                            f"{method.__name__}:"
                            f"{type(exc).__name__}:{exc}"
                        )

                if round_no == 0:
                    await asyncio.sleep(
                        0.30 + random.random() * 0.45
                    )

        raise StoreHttpError(
            "fetch_failed | "
            + " | ".join(errors[-8:])
        )
