from abc import ABC, abstractmethod
import asyncio
import os
import logging
import re
import httpx
from bs4 import BeautifulSoup
from ..models import DealCandidate

logger = logging.getLogger(__name__)

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")

def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    text = text.translate(ARABIC_DIGITS)
    text = text.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _browser_html(url: str, headers: dict) -> str:
    from playwright.sync_api import sync_playwright

    block_terms = (
        "robot check",
        "captcha",
        "verify you are human",
        "access denied",
        "unusual traffic",
        "تم رفض الوصول",
        "تحقق من أنك إنسان",
    )

    with sync_playwright() as pw:
        use_firefox = "noon.com" in str(url).lower()

        if use_firefox:
            print(
                "🦊 NOON DISCOVERY USING FIREFOX",
                flush=True,
            )
            browser = pw.firefox.launch(
                headless=True,
            )
        else:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                ],
            )

        context = browser.new_context(
            viewport={"width": 1360, "height": 950},
            locale="ar-EG",
            user_agent=headers.get(
                "User-Agent",
                "Mozilla/5.0 Chrome/140 Safari/537.36",
            ),
            extra_http_headers={
                "Accept-Language": headers.get(
                    "Accept-Language",
                    "ar-EG,ar;q=0.9,en;q=0.8",
                )
            },
        )

        page = context.new_page()

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=40000,
            )

            status = response.status if response else None

            if status in (403, 429, 503):
                raise RuntimeError(
                    f"browser_http_{status}"
                )

            page.wait_for_timeout(3000)

            try:
                body = page.locator("body").inner_text(
                    timeout=5000
                ).lower()
            except Exception:
                body = ""

            if any(term in body for term in block_terms):
                raise RuntimeError(
                    "browser_protection_page"
                )

            html = page.content()

            if len(html) < 5000:
                raise RuntimeError(
                    f"browser_html_too_small_{len(html)}"
                )

            return html

        finally:
            try:
                context.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass


class StoreConnector(ABC):
    name: str

    def __init__(self, timeout: float, user_agent: str):
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
        }

    async def _cloud_proxy_soup(self, client, url: str) -> BeautifulSoup:
        cloud_url = os.getenv("CLOUD_API_URL", "").strip()
        cloud_key = os.getenv("CLOUD_API_KEY", "").strip()

        if not cloud_url or not cloud_key:
            raise RuntimeError(f"{self.name}: cloud proxy unavailable")

        cloud_url = cloud_url.rstrip("/")
        if cloud_url.endswith("/api/deals"):
            cloud_url = cloud_url[:-len("/api/deals")]

        proxy_url = cloud_url + "/api/store-proxy"

        proxy = await client.get(
            proxy_url,
            params={"url": url},
            headers={
                "x-api-key": cloud_key,
                "Accept": "text/html",
            },
        )
        proxy.raise_for_status()

        logger.info(
            "%s Cloudflare proxy returned %s bytes",
            self.name,
            len(proxy.content),
        )
        return BeautifulSoup(proxy.text, "html.parser")

    async def get_soup(self, url: str) -> BeautifulSoup:
        if self.name in ("noon", "2b"):
            try:
                html = await asyncio.to_thread(
                    _browser_html,
                    url,
                    self.headers,
                )

                print(
                    f"🌐 {self.name} BROWSER "
                    f"bytes={len(html)}",
                    flush=True,
                )

                return BeautifulSoup(
                    html,
                    "html.parser",
                )

            except Exception as exc:
                print(
                    f"⚠️ {self.name} BROWSER FAILED "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:

            try:
                response = await client.get(url)
                response.raise_for_status()

                print(
                    f"✅ {self.name} DIRECT "
                    f"status={response.status_code} "
                    f"bytes={len(response.content)}",
                    flush=True,
                )

                return BeautifulSoup(
                    response.text,
                    "html.parser",
                )

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code

                if status not in (403, 429):
                    raise

                print(
                    f"⚠️ {self.name} DIRECT BLOCKED "
                    f"status={status}",
                    flush=True,
                )

            except (
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
                httpx.ConnectError,
            ) as exc:
                print(
                    f"⚠️ {self.name} DIRECT ERROR "
                    f"{type(exc).__name__}",
                    flush=True,
                )

            cloud_url = os.getenv(
                "CLOUD_API_URL",
                "",
            ).strip()

            cloud_key = os.getenv(
                "CLOUD_API_KEY",
                "",
            ).strip()

            if not cloud_url or not cloud_key:
                raise RuntimeError(
                    f"{self.name}: cloud proxy unavailable"
                )

            cloud_url = cloud_url.rstrip("/")

            if cloud_url.endswith("/api/deals"):
                cloud_url = cloud_url[:-len("/api/deals")]

            proxy_url = cloud_url + "/api/store-proxy"

            proxy = await client.get(
                proxy_url,
                params={"url": url},
                headers={
                    "x-api-key": cloud_key,
                    "Accept": "text/html",
                },
            )

            print(
                f"☁️ {self.name} PROXY "
                f"status={proxy.status_code} "
                f"bytes={len(proxy.content)}",
                flush=True,
            )

            proxy.raise_for_status()

            return BeautifulSoup(
                proxy.text,
                "html.parser",
            )

    @abstractmethod
    async def fetch_deals(self) -> list[DealCandidate]:
        raise NotImplementedError


# V12 compatibility adapter for proven legacy store connectors.
class Deal(DealCandidate):
    def __init__(
        self,
        store,
        title,
        current_price,
        url,
        old_price=None,
        image_url=None,
        external_id=None,
        metadata=None,
        **kwargs,
    ):
        key = (
            external_id
            or str(url).rstrip("/").split("/")[-1].split("?")[0]
            or str(title)[:80]
        )

        super().__init__(
            store=str(store),
            external_id=str(key),
            title=str(title),
            url=str(url),
            current_price=float(current_price),
            old_price=(
                float(old_price)
                if old_price is not None
                else None
            ),
            image_url=image_url,
            metadata=metadata or {},
        )
