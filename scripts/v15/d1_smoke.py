"""Manual-only V15 D1 smoke test. Creates and drops an isolated temporary table."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_dedup
from d1_monitoring_lease import query


def main():
    original = flash_dedup.TABLE
    table = 'v15_dedup_smoke_' + uuid.uuid4().hex[:16]
    flash_dedup.TABLE = table
    try:
        flash_dedup.initialize()
        candidate = {'asin': 'Z9TEST0001', 'current_price': '100.00'}
        sent = []
        def sender(item):
            sent.append(item['current_price'])
            return True
        assert flash_dedup.send_once(candidate, sender) == 'SENT'
        assert flash_dedup.send_once(candidate, sender) == 'SKIPPED_DUPLICATE'
        candidate['current_price'] = '91.00'
        assert flash_dedup.send_once(candidate, sender) == 'SKIPPED_DUPLICATE'
        candidate['current_price'] = '90.00'
        assert flash_dedup.send_once(candidate, sender) == 'SENT'
        assert len(sent) == 2
        rows = query(f'SELECT state,price_cents FROM {table} WHERE asin=\'Z9TEST0001\'')
        assert len(rows) == 1 and rows[0]['state'] == 'sent' and rows[0]['price_cents'] == 9000
        print('V15_D1_DEDUP_SMOKE_PASS isolated=true telegram=false public_post=false', flush=True)
    finally:
        flash_dedup.TABLE = original
        query(f'DROP TABLE IF EXISTS {table}')

if __name__ == '__main__':
    main()
