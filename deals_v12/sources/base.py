from abc import ABC, abstractmethod
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
