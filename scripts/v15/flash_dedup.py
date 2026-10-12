"""V15-only persistent Telegram alert dedup using Cloudflare D1.

A successful alert is not repeated unless its price drops by >=10%.
A claimed but unfinished send is retried after 10 minutes; Telegram delivery
and D1 acknowledgment cannot be perfectly atomic, so rare repeats are possible.
"""
from decimal import Decimal, InvalidOperation
import uuid
from d1_monitoring_lease import query, quote

TABLE = 'v15_flash_alert_dedup'


def initialize():
    query('''CREATE TABLE IF NOT EXISTS v15_flash_alert_dedup (
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
    price = cents(candidate['current_price'])
    owner = uuid.uuid4().hex
    # Claim only when: new ASIN, price improves >=10% from last alert,
    # or a sending lease expires. No repeat after a successful send.
    sql = f'''INSERT INTO {TABLE}(asin,price_cents,state,owner,updated_at)
    VALUES ({quote(asin)},{price},'sending',{quote(owner)},CURRENT_TIMESTAMP)
    ON CONFLICT(asin) DO UPDATE SET
      price_cents=excluded.price_cents, state='sending', owner=excluded.owner,
      updated_at=CURRENT_TIMESTAMP
    WHERE ({TABLE}.state='sent' AND excluded.price_cents*10 <= {TABLE}.price_cents*9)
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


def send_once(candidate, sender):
    owner = claim(candidate)
    if owner is None:
        return 'SKIPPED_DUPLICATE'
    delivered = bool(sender(candidate))
    finish(candidate['asin'], owner, delivered)
    return 'SENT' if delivered else 'SEND_FAILED_RETRY_LATER'
