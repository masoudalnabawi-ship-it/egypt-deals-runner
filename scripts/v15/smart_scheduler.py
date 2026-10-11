"""Amazon V15 adaptive scheduling policy.

Pure scheduling logic. No network access, Telegram or production changes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


INTERVALS = {
    "HOT": 3,
    "ACTIVE": 10,
    "STABLE": 30,
    "LOW": 60,
}

MAX_BACKOFF_MINUTES = 360


@dataclass(frozen=True)
class ProductState:
    asin: str
    priority: str = "STABLE"
    last_checked_at: datetime | None = None
    consecutive_errors: int = 0


def next_check_at(state: ProductState, now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")

    if state.priority not in INTERVALS:
        raise ValueError("Unknown priority")

    if state.consecutive_errors < 0:
        raise ValueError("Negative error count")

    if state.last_checked_at is None:
        return now

    if state.last_checked_at.tzinfo is None:
        raise ValueError("Timezone-aware last check required")

    minutes = INTERVALS[state.priority]

    if state.consecutive_errors:
        minutes = min(
            MAX_BACKOFF_MINUTES,
            minutes * (2 ** min(state.consecutive_errors, 10)),
        )

    return state.last_checked_at + timedelta(minutes=minutes)


def due_products(states, now, limit=20):
    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100")

    ready = []

    for state in states:
        due = next_check_at(state, now)

        if due <= now:
            ready.append((due, state))

    ready.sort(key=lambda item: (item[0], item[1].asin))

    return [state for _, state in ready[:limit]]
