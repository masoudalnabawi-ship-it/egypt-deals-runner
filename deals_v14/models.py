from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import re
import time


class Store(str, Enum):
    AMAZON = "amazon"
    NOON = "noon"


class Lane(str, Enum):
    NORMAL = "normal"
    ULTRA = "ultra"


class DealState(str, Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    DELIVERING = "delivering"
    SENT = "sent"
    RETRY = "retry"
    REJECTED = "rejected"


def now_ts() -> int:
    return int(time.time())


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def canonical_url(url: str) -> str:
    """Drop fragments and common tracking query strings without changing product identity."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlsplit(raw)
        # Product pages on both stores are stable without fragments.
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))
    except Exception:
        return raw


def normalize_external_id(store: str, external_id: str, url: str = "") -> str:
    value = _clean_text(external_id).upper()
    if value:
        return value

    if store.lower() == Store.AMAZON.value:
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", url, re.I)
        if m:
            return m.group(1).upper()

    if store.lower() == Store.NOON.value:
        m = re.search(r"/([A-Z0-9]{8,24})/p/?(?:\\?|$)", url, re.I)
        if m:
            return m.group(1).upper()

    return ""


@dataclass(slots=True)
class DealCandidate:
    store: str
    external_id: str
    title: str
    url: str
    current_price: float

    old_price: float | None = None
    image_url: str = ""
    category: str = "unknown"
    source: str = ""
    discovered_at: int = field(default_factory=now_ts)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.store = str(self.store).lower().strip()
        self.title = _clean_text(self.title)
        self.url = str(self.url or "").strip()
        self.image_url = str(self.image_url or "").strip()
        self.category = _clean_text(self.category) or "unknown"
        self.source = _clean_text(self.source)
        self.external_id = normalize_external_id(self.store, self.external_id, self.url)

        self.current_price = float(self.current_price or 0)
        if self.old_price is not None:
            self.old_price = float(self.old_price)
            if self.old_price <= self.current_price:
                self.old_price = None

    @property
    def discount_percent(self) -> float:
        if not self.old_price or self.old_price <= self.current_price or self.current_price <= 0:
            return 0.0
        return round(((self.old_price - self.current_price) / self.old_price) * 100, 2)

    @property
    def saving(self) -> float:
        if not self.old_price or self.old_price <= self.current_price:
            return 0.0
        return round(self.old_price - self.current_price, 2)

    @property
    def key(self) -> str:
        identity = self.external_id or canonical_url(self.url) or self.title.lower()
        raw = f"{self.store}|{identity}".encode("utf-8", "ignore")
        return sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        d["discount_percent"] = self.discount_percent
        d["saving"] = self.saving
        return d


@dataclass(slots=True)
class DealDecision:
    lane: Lane
    score: float
    confidence: float
    real_discount: float
    effective_price: float
    reasons: list[str] = field(default_factory=list)
    cross_store_price: float | None = None
    cross_store_store: str | None = None
    anomaly: bool = False
    flash: bool = False
    coupon_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lane"] = self.lane.value
        return d


@dataclass(slots=True)
class FetchResult:
    url: str
    text: str
    status_code: int
    via: str
    latency_ms: int
