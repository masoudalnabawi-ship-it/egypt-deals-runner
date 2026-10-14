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




def inspect_with_recovery(page, url, asin, inspector, blocked):
    """Retry once only for an incomplete, non-blocked page."""
    try:
        return inspector(page, url, asin)
    except RuntimeError as exc:
        if str(exc) != 'no_live_price':
            raise

        try:
            body = page.locator('body').inner_text(timeout=2500)
            incomplete = len(body.strip()) < 200
            if not incomplete or blocked(page):
                raise exc
        except RuntimeError:
            raise
        except Exception:
            raise exc

        print(
            'V16_SMART_RECOVERY',
            {'asin': asin, 'action': 'retry_incomplete_page'},
            flush=True,
        )
        return inspector(page, url, asin)




def verified_page_discount(page):
    """Read an explicitly advertised percentage from Amazon's product page."""
    selectors = (
        "#corePriceDisplay_desktop_feature_div .savingsPercentage",
        "#corePrice_feature_div .savingsPercentage",
        "#corePrice_desktop .savingsPercentage",
        ".savingsPercentage",
    )

    import re

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 5)

            for i in range(count):
                text = locator.nth(i).inner_text(timeout=1500)
                clean_text = re.sub(r"[\\u200e\\u200f\\u061c\\u202a-\\u202e\\u2066-\\u2069]", "", text)
                match = re.search(r"(100|[1-9]?[0-9])\\s*%", clean_text)

                if match:
                    value = int(match.group(1))
                    if 5 <= value <= 100:
                        return value
        except Exception:
            continue

    return None

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
                observation = inspect_with_recovery(page, f'https://www.amazon.eg/dp/{asin}', asin, v14.inspect_amazon, v14.page_blocked)
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
            try:
                discount_evidence = page.locator(
                    ".savingsPercentage, "
                    "[class*='savingsPercentage'], "
                    "#corePriceDisplay_desktop_feature_div .a-text-price, "
                    "#corePrice_feature_div .a-text-price"
                ).all_inner_texts()
                print("V16_DISCOUNT_EVIDENCE", {
                    "asin": asin,
                    "elements": [x.strip()[:100] for x in discount_evidence[:12]]
                }, flush=True)
            except Exception as exc:
                print("V16_DISCOUNT_EVIDENCE_ERROR", {
                    "asin": asin,
                    "reason": type(exc).__name__
                }, flush=True)
            verified_discount = verified_page_discount(page)
            offer = {'asin': asin, 'title': observation.get('title'),
                'current_price': observation.get('current_price'),
                'displayed_discount_pct': (
                    verified_discount if verified_discount is not None
                    else observation.get('savings_percent')
                )}
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
