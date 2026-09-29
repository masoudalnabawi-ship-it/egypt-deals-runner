from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
import threading
import time
import uuid

from ..models import DealCandidate, DealDecision, DealState, Lane


SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    deal_key TEXT PRIMARY KEY,
    store TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL DEFAULT '',
    current_price REAL NOT NULL,
    old_price REAL,
    effective_price REAL,
    visible_discount REAL NOT NULL DEFAULT 0,
    real_discount REAL NOT NULL DEFAULT 0,
    lane TEXT NOT NULL DEFAULT 'normal',
    score REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    discovered_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    verified_at INTEGER,
    sent_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_deals_state_lane_due
ON deals(state, lane, next_attempt_at, score DESC, discovered_at ASC);
CREATE INDEX IF NOT EXISTS idx_deals_store_updated
ON deals(store, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_category_updated
ON deals(category, updated_at DESC);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_key TEXT NOT NULL,
    store TEXT NOT NULL,
    price REAL NOT NULL,
    old_price REAL,
    observed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_key_time
ON price_history(deal_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS source_health (
    store TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    scans INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    candidates INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER NOT NULL DEFAULT 0,
    last_success_at INTEGER NOT NULL DEFAULT 0,
    last_latency_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(store, source)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    event TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    deal_key TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
"""


def _json(data) -> str:
    return json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"), default=str)


class DealDatabase:
    def __init__(self, path: str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init(self) -> None:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def tx(self):
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def event(self, event: str, store: str = "", deal_key: str = "", payload=None) -> None:
        self._conn().execute(
            "INSERT INTO events(ts,event,store,deal_key,payload_json) VALUES(?,?,?,?,?)",
            (int(time.time()), event, store, deal_key, _json(payload)),
        )

    def upsert_candidate(self, deal: DealCandidate, preliminary: DealDecision) -> dict:
        now = int(time.time())
        metadata = dict(deal.metadata or {})
        metadata["preliminary_reasons"] = preliminary.reasons

        with self.tx() as conn:
            old = conn.execute(
                "SELECT * FROM deals WHERE deal_key=?",
                (deal.key,),
            ).fetchone()

            should_reopen = False
            if old:
                old_price_now = float(old["current_price"] or 0)
                old_lane = old["lane"]
                price_improved = deal.current_price > 0 and (
                    old_price_now <= 0 or deal.current_price <= old_price_now * 0.985
                )
                lane_upgrade = old_lane != Lane.ULTRA.value and preliminary.lane == Lane.ULTRA
                stale_sent = old["state"] == DealState.SENT.value and price_improved
                should_reopen = lane_upgrade or stale_sent

                state = DealState.PENDING.value if should_reopen else old["state"]
                if state in {DealState.REJECTED.value, DealState.RETRY.value} and price_improved:
                    state = DealState.PENDING.value
                    should_reopen = True

                conn.execute(
                    """
                    UPDATE deals SET
                        external_id=?, title=?, url=?, image_url=?, category=?, source=?,
                        current_price=?, old_price=?, visible_discount=?, lane=?, score=?,
                        confidence=?, state=?, updated_at=?, next_attempt_at=?,
                        last_error=CASE WHEN ? THEN '' ELSE last_error END,
                        metadata_json=?
                    WHERE deal_key=?
                    """,
                    (
                        deal.external_id, deal.title, deal.url, deal.image_url,
                        deal.category, deal.source, deal.current_price, deal.old_price,
                        deal.discount_percent, preliminary.lane.value, preliminary.score,
                        preliminary.confidence, state, now,
                        0 if should_reopen else int(old["next_attempt_at"] or 0),
                        1 if should_reopen else 0,
                        _json(metadata), deal.key,
                    ),
                )
            else:
                should_reopen = True
                conn.execute(
                    """
                    INSERT INTO deals(
                        deal_key,store,external_id,title,url,image_url,category,source,
                        current_price,old_price,visible_discount,lane,score,confidence,
                        state,discovered_at,updated_at,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        deal.key, deal.store, deal.external_id, deal.title, deal.url,
                        deal.image_url, deal.category, deal.source, deal.current_price,
                        deal.old_price, deal.discount_percent, preliminary.lane.value,
                        preliminary.score, preliminary.confidence, DealState.PENDING.value,
                        deal.discovered_at, now, _json(metadata),
                    ),
                )

            recent_same = conn.execute(
                """SELECT 1 FROM price_history
                   WHERE deal_key=? AND ABS(price-?)<0.01 AND observed_at>?
                   LIMIT 1""",
                (deal.key, deal.current_price, now - 600),
            ).fetchone()
            if not recent_same:
                conn.execute(
                    "INSERT INTO price_history(deal_key,store,price,old_price,observed_at) VALUES(?,?,?,?,?)",
                    (deal.key, deal.store, deal.current_price, deal.old_price, now),
                )

        return {"new_or_reopened": should_reopen, "deal_key": deal.key}

    def claim_for_verification(
        self,
        store: str,
        lane: Lane,
        worker_id: str,
        lease_seconds: int,
    ) -> dict | None:
        now = int(time.time())
        with self.tx() as conn:
            row = conn.execute(
                """
                SELECT * FROM deals
                WHERE store=?
                  AND lane=?
                  AND state IN ('pending','retry')
                  AND next_attempt_at<=?
                  AND (lease_until=0 OR lease_until<?)
                ORDER BY score DESC, discovered_at ASC
                LIMIT 1
                """,
                (store, lane.value, now, now),
            ).fetchone()
            if not row:
                return None

            updated = conn.execute(
                """
                UPDATE deals SET state='verifying', lease_owner=?, lease_until=?, updated_at=?
                WHERE deal_key=? AND state IN ('pending','retry')
                """,
                (worker_id, now + lease_seconds, now, row["deal_key"]),
            ).rowcount
            if not updated:
                return None
            return dict(row)

    def mark_verified(self, deal_key: str, deal: DealCandidate, decision: DealDecision, metadata: dict) -> None:
        now = int(time.time())
        with self.tx() as conn:
            conn.execute(
                """
                UPDATE deals SET
                    external_id=?, title=?, url=?, image_url=?, category=?, source=?,
                    current_price=?, old_price=?, effective_price=?, visible_discount=?,
                    real_discount=?, lane=?, score=?, confidence=?, state='verified',
                    verified_at=?, updated_at=?, attempts=0, next_attempt_at=0,
                    lease_owner=NULL, lease_until=0, last_error='', metadata_json=?
                WHERE deal_key=?
                """,
                (
                    deal.external_id, deal.title, deal.url, deal.image_url, deal.category,
                    deal.source, deal.current_price, deal.old_price, decision.effective_price,
                    deal.discount_percent, decision.real_discount, decision.lane.value,
                    decision.score, decision.confidence, now, now, _json(metadata), deal_key,
                ),
            )
            conn.execute(
                "INSERT INTO price_history(deal_key,store,price,old_price,observed_at) VALUES(?,?,?,?,?)",
                (deal_key, deal.store, deal.current_price, deal.old_price, now),
            )
            conn.execute(
                "UPDATE source_health SET verified=verified+1 WHERE store=? AND source=?",
                (deal.store, deal.source),
            )

    def mark_rejected(self, deal_key: str, reason: str) -> None:
        now = int(time.time())
        self._conn().execute(
            """
            UPDATE deals SET state='rejected', last_error=?, updated_at=?,
                lease_owner=NULL, lease_until=0
            WHERE deal_key=?
            """,
            (reason[:500], now, deal_key),
        )

    def mark_retry(self, deal_key: str, reason: str, base_seconds: int, max_attempts: int) -> None:
        now = int(time.time())
        row = self._conn().execute(
            "SELECT attempts FROM deals WHERE deal_key=?", (deal_key,)
        ).fetchone()
        attempts = int(row["attempts"] if row else 0) + 1
        if attempts >= max_attempts:
            self.mark_rejected(deal_key, f"max_attempts:{reason}")
            return
        delay = min(3600, base_seconds * (2 ** max(0, attempts - 1)))
        self._conn().execute(
            """
            UPDATE deals SET state='retry', attempts=?, next_attempt_at=?,
                last_error=?, updated_at=?, lease_owner=NULL, lease_until=0
            WHERE deal_key=?
            """,
            (attempts, now + delay, reason[:500], now, deal_key),
        )

    def claim_for_delivery(self, lane: Lane, worker_id: str, lease_seconds: int) -> dict | None:
        now = int(time.time())
        with self.tx() as conn:
            row = conn.execute(
                """
                SELECT d.* FROM deals d
                WHERE d.lane=? AND d.state='verified'
                  AND d.next_attempt_at<=?
                  AND (d.lease_until=0 OR d.lease_until<?)
                ORDER BY
                  (SELECT COUNT(*) FROM deals s
                   WHERE s.state='sent' AND s.lane=d.lane
                     AND s.store=d.store AND s.sent_at>?) ASC,
                  (SELECT COUNT(*) FROM deals s
                   WHERE s.state='sent' AND s.lane=d.lane
                     AND s.category=d.category AND s.sent_at>?) ASC,
                  d.score DESC,
                  d.verified_at ASC
                LIMIT 1
                """,
                (lane.value, now, now, now - 21600, now - 21600),
            ).fetchone()
            if not row:
                return None
            updated = conn.execute(
                """
                UPDATE deals SET state='delivering', lease_owner=?, lease_until=?, updated_at=?
                WHERE deal_key=? AND state='verified'
                """,
                (worker_id, now + lease_seconds, now, row["deal_key"]),
            ).rowcount
            return dict(row) if updated else None

    def mark_sent(self, deal_key: str) -> None:
        now = int(time.time())
        with self.tx() as conn:
            row = conn.execute(
                "SELECT store,source FROM deals WHERE deal_key=?", (deal_key,)
            ).fetchone()
            conn.execute(
                """
                UPDATE deals SET state='sent', sent_at=?, updated_at=?,
                    lease_owner=NULL, lease_until=0, last_error=''
                WHERE deal_key=?
                """,
                (now, now, deal_key),
            )
            if row:
                conn.execute(
                    "UPDATE source_health SET sent=sent+1 WHERE store=? AND source=?",
                    (row["store"], row["source"]),
                )

    def delivery_retry(self, deal_key: str, reason: str, base_seconds: int, max_attempts: int) -> None:
        now = int(time.time())
        row = self._conn().execute(
            "SELECT attempts FROM deals WHERE deal_key=?", (deal_key,)
        ).fetchone()
        attempts = int(row["attempts"] if row else 0) + 1
        if attempts >= max_attempts:
            self.mark_rejected(deal_key, f"delivery_max_attempts:{reason}")
            return
        delay = min(1800, base_seconds * (2 ** max(0, attempts - 1)))
        self._conn().execute(
            """
            UPDATE deals SET state='verified', attempts=?, next_attempt_at=?,
                last_error=?, updated_at=?, lease_owner=NULL, lease_until=0
            WHERE deal_key=?
            """,
            (attempts, now + delay, reason[:500], now, deal_key),
        )

    def release_stale_leases(self) -> int:
        now = int(time.time())
        return self._conn().execute(
            """
            UPDATE deals SET
                state=CASE WHEN state='delivering' THEN 'verified' ELSE 'retry' END,
                lease_owner=NULL, lease_until=0, updated_at=?
            WHERE state IN ('verifying','delivering') AND lease_until>0 AND lease_until<?
            """,
            (now, now),
        ).rowcount

    def recent_prices(self, deal_key: str, limit: int = 30) -> list[float]:
        rows = self._conn().execute(
            """
            SELECT price FROM price_history WHERE deal_key=? AND price>0
            ORDER BY observed_at DESC LIMIT ?
            """,
            (deal_key, limit),
        ).fetchall()
        return [float(r["price"]) for r in rows]

    def recent_other_store(self, store: str, since_seconds: int = 7 * 86400, limit: int = 250) -> list[dict]:
        cutoff = int(time.time()) - since_seconds
        rows = self._conn().execute(
            """
            SELECT * FROM deals
            WHERE store<>? AND updated_at>=? AND current_price>0
              AND state IN ('verified','sent') AND confidence>=0.62
            ORDER BY updated_at DESC LIMIT ?
            """,
            (store, cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def source_result(
        self,
        store: str,
        source: str,
        category: str,
        fetched: int,
        candidates: int,
        latency_ms: int,
        error: str = "",
    ) -> None:
        now = int(time.time())
        with self.tx() as conn:
            conn.execute(
                """
                INSERT INTO source_health(
                    store,source,category,scans,fetched,candidates,errors,
                    consecutive_errors,last_attempt_at,last_success_at,last_latency_ms,last_error
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(store,source) DO UPDATE SET
                    category=excluded.category,
                    scans=source_health.scans+1,
                    fetched=source_health.fetched+excluded.fetched,
                    candidates=source_health.candidates+excluded.candidates,
                    errors=source_health.errors+excluded.errors,
                    consecutive_errors=CASE
                        WHEN excluded.errors>0 THEN source_health.consecutive_errors+1
                        ELSE 0 END,
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=CASE
                        WHEN excluded.errors=0 THEN excluded.last_attempt_at
                        ELSE source_health.last_success_at END,
                    last_latency_ms=excluded.last_latency_ms,
                    last_error=excluded.last_error
                """,
                (
                    store, source, category, 1, fetched, candidates, 1 if error else 0,
                    1 if error else 0, now, 0 if error else now, latency_ms, error[:500],
                ),
            )

    def source_health(self, store: str) -> dict[str, dict]:
        rows = self._conn().execute(
            "SELECT * FROM source_health WHERE store=?", (store,)
        ).fetchall()
        return {r["source"]: dict(r) for r in rows}

    def stats(self) -> dict:
        rows = self._conn().execute(
            "SELECT store,lane,state,COUNT(*) n FROM deals GROUP BY store,lane,state"
        ).fetchall()
        out = {}
        for r in rows:
            out.setdefault(r["store"], {}).setdefault(r["lane"], {})[r["state"]] = int(r["n"])
        return out

    def row_to_candidate(self, row: dict) -> DealCandidate:
        try:
            meta = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        return DealCandidate(
            store=row["store"],
            external_id=row.get("external_id") or "",
            title=row["title"],
            url=row["url"],
            current_price=float(row["current_price"]),
            old_price=float(row["old_price"]) if row.get("old_price") else None,
            image_url=row.get("image_url") or "",
            category=row.get("category") or "unknown",
            source=row.get("source") or "",
            discovered_at=int(row.get("discovered_at") or time.time()),
            metadata=meta,
        )
