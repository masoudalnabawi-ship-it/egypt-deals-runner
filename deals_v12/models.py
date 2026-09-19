from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import hashlib
import time


def now_ts() -> int:
    return int(time.time())


@dataclass
class DealCandidate:
    store: str
    external_id: str
    title: str
    url: str
    current_price: float

    old_price: Optional[float] = None
    image_url: str = ""
    discovered_at: int = field(default_factory=now_ts)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def saving(self) -> float:
        if not self.old_price or self.old_price <= self.current_price:
            return 0.0
        return round(self.old_price - self.current_price, 2)

    @property
    def discount_percent(self) -> float:
        if not self.old_price or self.old_price <= 0:
            return 0.0
        if self.old_price <= self.current_price:
            return 0.0

        return round(
            ((self.old_price - self.current_price) / self.old_price) * 100,
            2,
        )

    @property
    def fingerprint(self) -> str:
        identity = (
            self.external_id.strip()
            or self.url.strip()
            or self.title.strip()
        )

        raw = f"{self.store.lower()}|{identity.lower()}"

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["saving"] = self.saving
        data["discount_percent"] = self.discount_percent
        data["fingerprint"] = self.fingerprint
        return data


@dataclass
class StoreHealth:
    store: str
    status: str = "unknown"

    last_attempt_at: int = 0
    last_success_at: int = 0

    fetched_count: int = 0
    candidate_count: int = 0
    verified_count: int = 0
    review_count: int = 0

    total_errors: int = 0
    consecutive_failures: int = 0

    latency_ms: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
