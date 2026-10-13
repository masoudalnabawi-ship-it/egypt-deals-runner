"""Yield independently verified page data BEFORE capturing a screenshot.

Uses the existing V14 read-only page inspector, without its queue or D1.
The browser stays open across the first yield, so Telegram text can be sent
before screenshot generation begins. No challenge bypass is attempted.
"""
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



def probe_fast(asin):
    import v14_production_pipeline as v14
    if not isinstance(asin, str) or len(asin) != 10 or not asin.isascii() or not asin.isalnum():
        raise ValueError('INVALID_ASIN')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        opts = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
        chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
        if chrome:
            opts['executable_path'] = chrome
        browser = pw.chromium.launch(**opts)
        try:
            context = browser.new_context(locale='ar-EG', timezone_id='Africa/Cairo',
                user_agent=v14.UA, viewport={'width': 1440, 'height': 1800})
            page = context.new_page()
            try:
                observation = v14.inspect_amazon(page, f'https://www.amazon.eg/dp/{asin}', asin)
            except RuntimeError as exc:
                if str(exc) == 'no_live_price':
                    try:
                        title = page.title()
                        body = page.locator('body').inner_text(timeout=2500)
                        body_length = len(body.strip())
                        has_product_title = page.locator('#productTitle').count() > 0
                        has_buybox = page.locator('#buybox, #desktop_buybox').count() > 0

                        if body_length < 200:
                            diagnosis = 'EMPTY_OR_INCOMPLETE_PAGE'
                        elif not has_product_title and not has_buybox:
                            diagnosis = 'NON_PRODUCT_PAGE'
                        else:
                            diagnosis = 'PRODUCT_PAGE_WITHOUT_PRICE'

                        print(
                            'V16_PAGE_DIAGNOSTIC',
                            {
                                'asin': asin,
                                'diagnosis': diagnosis,
                                'title': title[:100],
                                'body_length': body_length,
                                'has_product_title': has_product_title,
                                'has_buybox': has_buybox,
                            },
                            flush=True,
                        )
                        raise RuntimeError('no_live_price:' + diagnosis) from exc
                    except RuntimeError as diagnostic_error:
                        if str(diagnostic_error).startswith('no_live_price:'):
                            raise
                        raise exc
                    except Exception:
                        raise exc
                raise
            if observation.get('page_asin') != asin:
                raise ValueError('PAGE_ASIN_MISMATCH')
            offer = {'asin': asin, 'title': observation.get('title'),
                'current_price': observation.get('current_price'),
                'displayed_discount_pct': observation.get('savings_percent')}
            # First yield happens BEFORE screenshot capture, not after it.
            yield offer, None, None
            with tempfile.TemporaryDirectory(prefix='v16-image-') as directory:
                image = Path(directory) / 'amazon-real-screenshot.jpg'
                v14.capture_product_screenshot(page, image)
                if not image.is_file() or image.stat().st_size == 0:
                    raise RuntimeError('SCREENSHOT_MISSING')
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                yield offer, image, digest
        finally:
            browser.close()
