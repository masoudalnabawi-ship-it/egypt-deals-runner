"""V15-only persistent Telegram alert dedup using Cloudflare D1.

A successful alert is not repeated unless its price drops by >=10%.
A claimed but unfinished send is retried after 10 minutes; Telegram delivery
and D1 acknowledgment cannot be perfectly atomic, so rare repeats are possible.
"""
from decimal import Decimal, InvalidOperation
import uuid
from d1_monitoring_lease import query, quote

TABLE = 'v15_flash_alert_dedup'
SCREENSHOT_TABLE = 'v15_flash_screenshot_dedup'


def initialize():
    query(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
        asin TEXT PRIMARY KEY,
        price_cents INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('sending','sent')),
        owner TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')


def cents(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError('INVALID_FLASH_PRICE')
        return int((number * 100).quantize(Decimal('1')))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('INVALID_FLASH_PRICE') from exc


def claim(candidate):
    asin = candidate['asin']
    if not isinstance(asin, str) or len(asin) != 10 or not asin.isalnum() or asin != asin.upper():
        raise ValueError('INVALID_ASIN')
    raw_price = candidate.get('current_price')
    if raw_price is None:
        discount = Decimal(str(candidate.get('displayed_discount_pct', 0)))
        if not discount.is_finite() or not 1 <= discount <= 100:
            raise ValueError('INVALID_DISPLAYED_DISCOUNT')
        price = 0
    else:
        price = cents(raw_price)
    owner = uuid.uuid4().hex
    # Claim only when: new ASIN, price improves >=10% from last alert,
    # or a sending lease expires. No repeat after a successful send.
    sql = f'''INSERT INTO {TABLE}(asin,price_cents,state,owner,updated_at)
    VALUES ({quote(asin)},{price},'sending',{quote(owner)},CURRENT_TIMESTAMP)
    ON CONFLICT(asin) DO UPDATE SET
      price_cents=excluded.price_cents, state='sending', owner=excluded.owner,
      updated_at=CURRENT_TIMESTAMP
    WHERE ({TABLE}.state='sent' AND excluded.price_cents>0 AND {TABLE}.price_cents>0 AND excluded.price_cents*10 <= {TABLE}.price_cents*9)
       OR ({TABLE}.state='sending' AND {TABLE}.updated_at <= datetime('now','-10 minutes'))
    RETURNING owner'''
    rows = query(sql)
    if not rows:
        return None
    if len(rows) != 1 or rows[0].get('owner') != owner:
        raise RuntimeError('V15_FLASH_DEDUP_CLAIM_INVARIANT')
    return owner


def finish(asin, owner, sent):
    if sent:
        query(f"UPDATE {TABLE} SET state='sent', updated_at=CURRENT_TIMESTAMP "
              f"WHERE asin={quote(asin)} AND owner={quote(owner)} AND state='sending'")
    else:
        # Keep sending lease to avoid repeated alerts on intermittent failures.
        # Retry will be permitted after the lease expires.
        pass



def send_screenshot_once(candidate, sender):
    """One private screenshot update per ASIN, with retry on failure."""
    if not candidate.get("screenshot_path") or not candidate.get("screenshot_sha256"):
        return "SCREENSHOT_NOT_READY"

    asin = candidate["asin"]
    if not isinstance(asin, str) or len(asin) != 10 or not asin.isalnum() or asin != asin.upper():
        raise ValueError("INVALID_ASIN")

    query(f"""CREATE TABLE IF NOT EXISTS {SCREENSHOT_TABLE} (
        asin TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK(state IN ('sending','sent')),
        owner TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")

    owner = uuid.uuid4().hex
    rows = query(f"""INSERT INTO {SCREENSHOT_TABLE}
        (asin,state,owner,updated_at)
        VALUES ({quote(asin)},'sending',{quote(owner)},CURRENT_TIMESTAMP)
        ON CONFLICT(asin) DO UPDATE SET
          state='sending',owner=excluded.owner,updated_at=CURRENT_TIMESTAMP
        WHERE {SCREENSHOT_TABLE}.state='sending'
          AND {SCREENSHOT_TABLE}.updated_at <= datetime('now','-10 minutes')
        RETURNING owner""")

    if not rows:
        return "SKIPPED_SCREENSHOT_DUPLICATE"

    if len(rows) != 1 or rows[0].get("owner") != owner:
        raise RuntimeError("V15_SCREENSHOT_DEDUP_CLAIM_INVARIANT")

    delivered = bool(sender(candidate))

    if delivered:
        query(f"""UPDATE {SCREENSHOT_TABLE}
            SET state='sent',updated_at=CURRENT_TIMESTAMP
            WHERE asin={quote(asin)}
              AND owner={quote(owner)}
              AND state='sending'""")

    return "SCREENSHOT_SENT" if delivered else "SCREENSHOT_RETRY_LATER"


def send_once(candidate, sender):
    owner = claim(candidate)
    if owner is None:
        return 'SKIPPED_DUPLICATE'
    delivered = bool(sender(candidate))
    finish(candidate['asin'], owner, delivered)
    return 'SENT' if delivered else 'SEND_FAILED_RETRY_LATER'
