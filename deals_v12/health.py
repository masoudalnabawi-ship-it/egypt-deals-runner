from pathlib import Path
from threading import Lock
import json
import time

from .models import StoreHealth, now_ts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / ".runtime_state" / "v12_health.json"


class HealthMonitor:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.health = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return

        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8")
            )

            for store, values in data.items():
                self.health[store] = StoreHealth(**values)

        except Exception:
            self.health = {}

    def _get(self, store):
        key = str(store).strip().lower()

        if key not in self.health:
            self.health[key] = StoreHealth(store=key)

        return self.health[key]

    def _save(self):
        data = {
            store: item.to_dict()
            for store, item in self.health.items()
        }

        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def mark_attempt(self, store):
        with self.lock:
            item = self._get(store)
            item.status = "checking"
            item.last_attempt_at = now_ts()
            self._save()

    def mark_success(
        self,
        store,
        fetched=0,
        candidates=0,
        verified=0,
        reviews=0,
        latency_ms=0,
    ):
        with self.lock:
            item = self._get(store)
            item.status = "healthy"
            item.last_attempt_at = now_ts()
            item.last_success_at = now_ts()
            item.fetched_count = int(fetched)
            item.candidate_count = int(candidates)
            item.verified_count = int(verified)
            item.review_count = int(reviews)
            item.latency_ms = int(latency_ms)
            item.consecutive_failures = 0
            item.last_error = ""
            self._save()

    def mark_error(self, store, error, latency_ms=0):
        with self.lock:
            item = self._get(store)
            item.status = "error"
            item.last_attempt_at = now_ts()
            item.total_errors += 1
            item.consecutive_failures += 1
            item.latency_ms = int(latency_ms)
            item.last_error = str(error)[:500]
            self._save()

    def snapshot(self):
        with self.lock:
            return {
                store: item.to_dict()
                for store, item in self.health.items()
            }

    def status_text(self):
        rows = ["🛰 Egypt Deals V12 — Health", ""]
        now = int(time.time())

        for store in ("amazon", "noon", "btech", "2b"):
            item = self._get(store)

            icon = {
                "healthy": "🟢",
                "checking": "🟡",
                "error": "🔴",
            }.get(item.status, "⚪")

            if item.last_success_at:
                age = max(0, now - item.last_success_at)
                age_text = f"{age}s ago"
            else:
                age_text = "never"

            rows.append(
                f"{icon} {store.upper()}"
                f" | fetched={item.fetched_count}"
                f" | candidates={item.candidate_count}"
                f" | verified={item.verified_count}"
                f" | reviews={item.review_count}"
                f" | success={age_text}"
            )

            if item.last_error:
                rows.append(f"   ↳ {item.last_error}")

        return "\n".join(rows)
