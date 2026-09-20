import json
import time
from pathlib import Path

from .models import DealCandidate
from .state import connect, init_db


SEEN_LEDGER = Path(".runtime_state/v12_seen_ledger.json")


def _load_seen_ledger():
    try:
        if SEEN_LEDGER.is_file():
            return json.loads(SEEN_LEDGER.read_text())
    except Exception:
        pass
    return {}


def _save_seen_ledger(data):
    SEEN_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_LEDGER.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True)
    )
    tmp.replace(SEEN_LEDGER)



class DealQueue:
    def __init__(self):
        init_db()

    def _seen_key(self, deal: DealCandidate):
        return (
            f"{deal.store.lower()}|"
            f"{deal.external_id.strip().lower()}|"
            f"{float(deal.current_price or 0):.2f}"
        )

    def was_seen_exact(self, deal: DealCandidate):
        ledger = _load_seen_ledger()
        return self._seen_key(deal) in ledger

    def remember_seen_exact(self, deal: DealCandidate):
        ledger = _load_seen_ledger()
        key = self._seen_key(deal)

        ledger[key] = {
            "store": deal.store.lower(),
            "external_id": deal.external_id,
            "price": float(deal.current_price or 0),
            "seen_at": int(time.time()),
        }

        # Keep ledger bounded.
        if len(ledger) > 20000:
            items = sorted(
                ledger.items(),
                key=lambda kv: kv[1].get("seen_at", 0),
                reverse=True,
            )[:15000]
            ledger = dict(items)

        _save_seen_ledger(ledger)

    def enqueue(self, deal: DealCandidate, priority=0):
        now = int(time.time())
        fp = deal.fingerprint
        payload = json.dumps(
            deal.to_dict(),
            ensure_ascii=False,
        )

        with connect() as con:
            row = con.execute(
                """
                SELECT payload,status,priority
                FROM queue_items
                WHERE fingerprint=?
                """,
                (fp,),
            ).fetchone()

            if row is None:
                if self.was_seen_exact(deal):
                    return "seen_exact"

                con.execute(
                    """
                    INSERT INTO queue_items(
                        fingerprint,
                        store,
                        payload,
                        status,
                        priority,
                        attempts,
                        next_attempt_at,
                        discovered_at,
                        updated_at
                    )
                    VALUES(?,?,?,'pending',?,0,0,?,?)
                    """,
                    (
                        fp,
                        deal.store.lower(),
                        payload,
                        int(priority),
                        deal.discovered_at,
                        now,
                    ),
                )

                con.commit()
                return "new"

            try:
                old = json.loads(row["payload"])
            except Exception:
                old = {}

            old_price = float(
                old.get("current_price") or 0
            )

            new_price = float(
                deal.current_price or 0
            )

            old_discount = float(
                old.get("discount_percent") or 0
            )

            new_discount = float(
                deal.discount_percent or 0
            )

            price_drop_percent = (
                ((old_price - new_price) / old_price) * 100
                if old_price > 0 and new_price > 0 and new_price < old_price
                else 0.0
            )

            # Do not re-send an already known product for tiny fluctuations.
            # Re-open only when the offer became materially better.
            price_improved = (
                price_drop_percent >= 5.0
            )

            discount_improved = (
                new_discount >= old_discount + 5.0
            )

            reopen = (
                price_improved
                or discount_improved
            )

            status = row["status"]

            if reopen:
                status = "pending"

            con.execute(
                """
                UPDATE queue_items
                SET payload=?,
                    store=?,
                    status=?,
                    priority=?,
                    next_attempt_at=?,
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    payload,
                    deal.store.lower(),
                    status,
                    max(
                        int(row["priority"] or 0),
                        int(priority),
                    ),
                    0 if reopen else now,
                    now,
                    fp,
                ),
            )

            con.commit()

            return (
                "reopened"
                if reopen
                else "updated"
            )

    def get_due(self, limit=20):
        now = int(time.time())

        with connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM queue_items
                WHERE status IN ('pending','retry')
                  AND next_attempt_at <= ?
                ORDER BY priority DESC,
                         discovered_at ASC
                LIMIT ?
                """,
                (
                    now,
                    int(limit),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_verified(self, limit=10):
        with connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM queue_items
                WHERE status='verified'
                ORDER BY priority DESC, discovered_at ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def mark_processing(self, fingerprint):
        now = int(time.time())

        with connect() as con:
            con.execute(
                """
                UPDATE queue_items
                SET status='processing',
                    attempts=attempts+1,
                    updated_at=?
                WHERE fingerprint=?
                """,
                (now, fingerprint),
            )
            con.commit()

    def mark_retry(self, fingerprint, error=""):
        now = int(time.time())

        with connect() as con:
            row = con.execute(
                """
                SELECT attempts
                FROM queue_items
                WHERE fingerprint=?
                """,
                (fingerprint,),
            ).fetchone()

            attempts = (
                int(row["attempts"] or 0)
                if row
                else 1
            )

            delays = (
                30,
                60,
                120,
                300,
                600,
                900,
                1800,
                3600,
            )

            delay = delays[
                min(
                    max(attempts - 1, 0),
                    len(delays) - 1,
                )
            ]

            con.execute(
                """
                UPDATE queue_items
                SET status='retry',
                    next_attempt_at=?,
                    last_error=?,
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    now + delay,
                    str(error)[:1000],
                    now,
                    fingerprint,
                ),
            )
            con.commit()

        return delay

    def mark_reviewed(
        self,
        fingerprint,
        message_id=None,
    ):
        now = int(time.time())

        with connect() as con:
            con.execute(
                """
                UPDATE queue_items
                SET status='reviewed',
                    review_message_id=?,
                    last_error='',
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    message_id,
                    now,
                    fingerprint,
                ),
            )
            con.commit()

    def mark_rejected(self, fingerprint):
        now = int(time.time())

        with connect() as con:
            con.execute(
                """
                UPDATE queue_items
                SET status='rejected',
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    now,
                    fingerprint,
                ),
            )
            con.commit()

    def recover_stuck(self, max_age=300):
        now = int(time.time())
        cutoff = now - int(max_age)

        with connect() as con:
            cur = con.execute(
                """
                UPDATE queue_items
                SET status='retry',
                    next_attempt_at=?,
                    last_error='recovered_after_interrupted_worker',
                    updated_at=?
                WHERE status='processing'
                  AND updated_at < ?
                """,
                (
                    now,
                    now,
                    cutoff,
                ),
            )

            recovered = cur.rowcount
            con.commit()

        return recovered

    def stats(self):
        with connect() as con:
            rows = con.execute(
                """
                SELECT status,COUNT(*) AS count
                FROM queue_items
                GROUP BY status
                """
            ).fetchall()

        return {
            row["status"]: int(row["count"])
            for row in rows
        }

    def mark_verified(self, fingerprint, verification):
        now = int(time.time())

        with connect() as con:
            row = con.execute(
                """
                SELECT payload
                FROM queue_items
                WHERE fingerprint=?
                """,
                (fingerprint,),
            ).fetchone()

            if row is None:
                return False

            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {}

            payload["current_price"] = verification.get(
                "current_price",
                payload.get("current_price"),
            )

            payload["old_price"] = verification.get(
                "old_price",
                payload.get("old_price"),
            )

            metadata = payload.get("metadata") or {}
            metadata["verification"] = verification
            metadata["verified_at"] = now
            payload["metadata"] = metadata

            con.execute(
                """
                UPDATE queue_items
                SET payload=?,
                    status='verified',
                    next_attempt_at=0,
                    last_error='',
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                    now,
                    fingerprint,
                ),
            )

            con.commit()

        return True

    def mark_invalid(self, fingerprint, reason=""):
        now = int(time.time())

        with connect() as con:
            con.execute(
                """
                UPDATE queue_items
                SET status='invalid',
                    last_error=?,
                    updated_at=?
                WHERE fingerprint=?
                """,
                (
                    str(reason)[:1000],
                    now,
                    fingerprint,
                ),
            )

            con.commit()
