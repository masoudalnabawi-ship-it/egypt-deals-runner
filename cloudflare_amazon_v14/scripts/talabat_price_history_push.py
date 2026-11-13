"""Archive real observed Talabat prices, including non-discounted products.

Records only storefront observations. Never treats displayed originalPrice
as an independently verified historical price. Never publishes publicly.
"""
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

INPUT = Path('reports/talabat_price_observations.json')
TARGET = os.environ.get('REVIEW_WORKER_URL', '').rstrip('/')
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
if not TARGET.startswith('https://egypt-talabat-review.') or not TARGET.endswith('.workers.dev'):
    raise SystemExit('INVALID_TALABAT_HISTORY_WORKER_URL')
if not TOKEN:
    raise SystemExit('TALABAT_HISTORY_TOKEN_MISSING')
if not INPUT.is_file():
    raise SystemExit('TALABAT_PRICE_OBSERVATIONS_MISSING')

obj = json.loads(INPUT.read_text(encoding='utf-8'))
rows = obj.get('observations')
if not isinstance(rows, list):
    raise SystemExit('INVALID_HISTORY_REPORT')
if not rows:
    print('TALABAT_HISTORY: NO_PRODUCTS_IN_SCAN', flush=True)
    raise SystemExit(0)

success = 0
BATCH = 70
for start in range(0, len(rows), BATCH):
    batch = rows[start:start+BATCH]
    payload = json.dumps({'rows': batch}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    error = None
    for attempt in range(4):
        req = Request(TARGET + '/price-history/ingest', data=payload, method='POST', headers={
            'Authorization': 'Bearer ' + TOKEN,
            'Content-Type': 'application/json',
            'User-Agent': 'TalabatPriceHistory/1.0'
        })
        try:
            with urlopen(req, timeout=30) as resp:
                result = json.load(resp)
            if not result.get('ok') or result.get('accepted') != len(batch):
                raise RuntimeError('PRICE_HISTORY_WORKER_REJECTED_BATCH')
            success += len(batch)
            error = None
            break
        except HTTPError as exc:
            # Do not retry authentication or validation failures.
            if exc.code not in (429, 500, 502, 503, 504):
                raise SystemExit('PRICE_HISTORY_WORKER_HTTP_' + str(exc.code))
            error = type(exc).__name__ + '_' + str(exc.code)
        except (URLError, TimeoutError) as exc:
            error = type(exc).__name__
        if attempt < 3:
            time.sleep(min(2 ** attempt, 5))
    if error:
        raise SystemExit('PRICE_HISTORY_UPLOAD_FAILED: ' + error)

print('TALABAT_PRICE_HISTORY_SAVED:', success, 'of', len(rows), flush=True)
print('PRICE_BASELINE: historic comparisons will improve as independent days accumulate', flush=True)
