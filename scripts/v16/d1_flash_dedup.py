"""V16-only persistent D1 dedup; separate tables from V15."""
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from d1_monitoring_lease import query, quote

TEXT_TABLE = 'v16_flash_alert_dedup'
PHOTO_TABLE = 'v16_flash_screenshot_dedup'


def cents(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError('INVALID_PRICE')
        return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('INVALID_PRICE') from exc


def validate(candidate):
    asin = candidate.get('asin')
    if not isinstance(asin, str) or not re.fullmatch(r'[A-Z0-9]{10}', asin):
        raise ValueError('INVALID_ASIN')
    return asin, cents(candidate.get('current_price'))


def initialize():
    query(f"""CREATE TABLE IF NOT EXISTS {TEXT_TABLE} (
        asin TEXT PRIMARY KEY,
        price_cents INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('sending','sent')),
        owner TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    query(f"""CREATE TABLE IF NOT EXISTS {PHOTO_TABLE} (
        asin TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        screenshot_sha256 TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('sending','sent')),
        owner TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (asin,price_cents,screenshot_sha256)
    )""")


def send_once(candidate, sender):
    asin, price = validate(candidate)
    owner = uuid.uuid4().hex

    rows = query(f"""INSERT INTO {TEXT_TABLE}
        (asin,price_cents,state,owner,updated_at)
        VALUES ({quote(asin)},{price},'sending',{quote(owner)},CURRENT_TIMESTAMP)
        ON CONFLICT(asin) DO UPDATE SET
            price_cents=excluded.price_cents,
            state='sending',
            owner=excluded.owner,
            updated_at=CURRENT_TIMESTAMP
        WHERE ({TEXT_TABLE}.state='sent'
               AND excluded.price_cents < {TEXT_TABLE}.price_cents)
           OR ({TEXT_TABLE}.state='sending'
               AND {TEXT_TABLE}.updated_at <= datetime('now','-10 minutes'))
        RETURNING owner""")

    if not rows:
        return 'SKIPPED_DUPLICATE'
    if len(rows) != 1 or rows[0].get('owner') != owner:
        raise RuntimeError('V16_TEXT_CLAIM_INVARIANT')

    try:
        delivered = bool(sender(candidate))
    except Exception:
        delivered = False

    if delivered:
        query(f"""UPDATE {TEXT_TABLE}
            SET state='sent',updated_at=CURRENT_TIMESTAMP
            WHERE asin={quote(asin)} AND owner={quote(owner)}
              AND state='sending'""")

    return 'SENT' if delivered else 'SEND_FAILED_RETRY_LATER'


def send_screenshot_once(candidate, sender):
    asin, price = validate(candidate)
    digest = candidate.get('screenshot_sha256')

    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
        return 'SCREENSHOT_NOT_READY'

    owner = uuid.uuid4().hex

    rows = query(f"""INSERT INTO {PHOTO_TABLE}
        (asin,price_cents,screenshot_sha256,state,owner,updated_at)
        VALUES ({quote(asin)},{price},{quote(digest)},'sending',
                {quote(owner)},CURRENT_TIMESTAMP)
        ON CONFLICT(asin,price_cents,screenshot_sha256) DO UPDATE SET
            state='sending',
            owner=excluded.owner,
            updated_at=CURRENT_TIMESTAMP
        WHERE {PHOTO_TABLE}.state='sending'
          AND {PHOTO_TABLE}.updated_at <= datetime('now','-10 minutes')
        RETURNING owner""")

    if not rows:
        return 'SKIPPED_SCREENSHOT_DUPLICATE'
    if len(rows) != 1 or rows[0].get('owner') != owner:
        raise RuntimeError('V16_PHOTO_CLAIM_INVARIANT')

    try:
        delivered = bool(sender(candidate))
    except Exception:
        delivered = False

    if delivered:
        query(f"""UPDATE {PHOTO_TABLE}
            SET state='sent',updated_at=CURRENT_TIMESTAMP
            WHERE asin={quote(asin)}
              AND price_cents={price}
              AND screenshot_sha256={quote(digest)}
              AND owner={quote(owner)}
              AND state='sending'""")

    return 'SCREENSHOT_SENT' if delivered else 'SCREENSHOT_RETRY_LATER'
