from __future__ import annotations

from dataclasses import dataclass
import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: str
    cloud_api_url: str
    cloud_api_key: str

    telegram_token: str
    normal_chat_id: str
    ultra_chat_id: str
    noon_normal_chat_id: str
    noon_ultra_chat_id: str

    ultra_min_discount: float
    normal_min_discount: float
    min_confidence_normal: float
    min_confidence_ultra: float

    discovery_interval: int
    verification_interval: int
    delivery_interval: int
    health_interval: int
    verification_workers_per_store: int
    max_attempts: int
    retry_base_seconds: int
    lease_seconds: int

    amazon_proxy_first: bool
    noon_proxy_first: bool
    exploration_rate: float
    surface_batch_size: int

    @classmethod
    def from_env(cls) -> "Settings":
        normal = (
            os.getenv("V13_NORMAL_REVIEW_CHAT_ID", "").strip()
            or os.getenv("REVIEW_CHAT_ID", "").strip()
            or os.getenv("AMAZON_NORMAL_REVIEW_CHAT_ID", "").strip()
        )
        ultra = (
            os.getenv("V13_ULTRA_REVIEW_CHAT_ID", "").strip()
            or os.getenv("AMAZON_REVIEW_GROUP_ID", "").strip()
        )

        return cls(
            db_path=os.getenv("V13_DB_PATH", ".runtime_state/v13.db").strip(),
            cloud_api_url=os.getenv("CLOUD_API_URL", "").strip(),
            cloud_api_key=os.getenv("CLOUD_API_KEY", "").strip(),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            normal_chat_id=normal,
            ultra_chat_id=ultra,
            noon_normal_chat_id=(
                os.getenv("NOON_NORMAL_REVIEW_CHAT_ID", "").strip() or normal
            ),
            noon_ultra_chat_id=(
                os.getenv("NOON_ULTRA_REVIEW_CHAT_ID", "").strip() or ultra
            ),
            ultra_min_discount=_float("V13_ULTRA_MIN_DISCOUNT", 50.0),
            normal_min_discount=_float("V13_NORMAL_MIN_DISCOUNT", 10.0),
            min_confidence_normal=_float("V13_MIN_CONFIDENCE_NORMAL", 0.62),
            min_confidence_ultra=_float("V13_MIN_CONFIDENCE_ULTRA", 0.76),
            discovery_interval=max(5, _int("V13_DISCOVERY_INTERVAL", 20)),
            verification_interval=max(1, _int("V13_VERIFICATION_INTERVAL", 2)),
            delivery_interval=max(1, _int("V13_DELIVERY_INTERVAL", 2)),
            health_interval=max(15, _int("V13_HEALTH_INTERVAL", 60)),
            verification_workers_per_store=max(1, _int("V13_VERIFY_WORKERS_PER_STORE", 2)),
            max_attempts=max(1, _int("V13_MAX_ATTEMPTS", 5)),
            retry_base_seconds=max(5, _int("V13_RETRY_BASE_SECONDS", 30)),
            lease_seconds=max(30, _int("V13_LEASE_SECONDS", 180)),
            amazon_proxy_first=_bool("V13_AMAZON_PROXY_FIRST", False),
            noon_proxy_first=_bool("V13_NOON_PROXY_FIRST", True),
            exploration_rate=min(0.8, max(0.05, _float("V13_EXPLORATION_RATE", 0.22))),
            surface_batch_size=max(1, _int("V13_SURFACE_BATCH_SIZE", 5)),
        )
