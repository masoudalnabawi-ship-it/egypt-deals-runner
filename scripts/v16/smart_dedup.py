"""Independent V16 SQLite alert ledger. Requires a persistent DB path across runs.

A successful alert is never repeated at the same/higher price. Any strictly lower
price can trigger an update. Unfinished claims are retried after a lease expires.
The Telegram API and local DB are not transactional: rare repeats remain possible.
"""
import os
import re
import sqlite3
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

LEASE_SECONDS = 600

def price_cents(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0:
            raise ValueError('INVALID_PRICE')
        return int((d * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('INVALID_PRICE') from exc

def database_path():
    path = os.environ.get('V16_DEDUP_DB', '').strip()
    if not path:
        raise RuntimeError('V16_DEDUP_DB_REQUIRED: use a persistent absolute file path')
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise RuntimeError('V16_DEDUP_DB_MUST_BE_ABSOLUTE')
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def connect():
    db = sqlite3.connect(str(database_path()), timeout=20, isolation_level=None)
    db.execute('PRAGMA busy_timeout=20000')
    db.execute('''CREATE TABLE IF NOT EXISTS alerts (
        asin TEXT PRIMARY KEY, price_cents INTEGER NOT NULL,
        state TEXT NOT NULL, owner TEXT NOT NULL, updated_at REAL NOT NULL)''')
    return db

def validate(candidate):
    asin = candidate.get('asin')
    if not isinstance(asin, str) or not re.fullmatch(r'[A-Z0-9]{10}', asin):
        raise ValueError('INVALID_ASIN')
    return asin, price_cents(candidate.get('current_price'))

def send_once(candidate, sender):
    asin, price = validate(candidate)
    owner = uuid.uuid4().hex
    now = time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT price_cents,state,updated_at FROM alerts WHERE asin=?', (asin,)).fetchone()
        if row and (row[1] == 'sent' and price >= row[0] or row[1] == 'sending' and now-row[2] < LEASE_SECONDS):
            db.execute('COMMIT')
            return 'SKIPPED_DUPLICATE'
        db.execute('''INSERT INTO alerts(asin,price_cents,state,owner,updated_at)
            VALUES (?,?,'sending',?,?) ON CONFLICT(asin) DO UPDATE SET
            price_cents=excluded.price_cents,state='sending',owner=excluded.owner,updated_at=excluded.updated_at''',
            (asin, price, owner, now))
        db.execute('COMMIT')
    try:
        delivered = bool(sender(candidate))
    except Exception:
        delivered = False
    with connect() as db:
        if delivered:
            db.execute("UPDATE alerts SET state='sent',updated_at=? WHERE asin=? AND owner=? AND state='sending'", (time.time(), asin, owner))
        else:
            # Failed sends may retry immediately, but only if the same owner still holds the claim.
            db.execute("DELETE FROM alerts WHERE asin=? AND owner=? AND state='sending'", (asin, owner))
    return 'SENT' if delivered else 'SEND_FAILED_RETRY_LATER'


def already_sent(candidate):
    """Read-only early duplicate check; final send_once remains authoritative."""
    asin, price = validate(candidate)
    with connect() as db:
        row = db.execute(
            'SELECT price_cents, state, updated_at FROM alerts WHERE asin=?',
            (asin,),
        ).fetchone()

    if row is None:
        return False

    old_price, state, updated_at = row

    if state == 'sent' and price >= old_price:
        return True

    if state == 'sending' and time.time() - updated_at < LEASE_SECONDS:
        return True

    return False
