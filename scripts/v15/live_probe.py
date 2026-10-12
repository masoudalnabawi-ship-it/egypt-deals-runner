"""Amazon V15 isolated live browser probe. No Telegram or queue calls."""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

# Reuse V14's proven page inspection and screenshot functions.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import v14_production_pipeline as v14


def main():
    asin = os.environ.get("V15_TEST_ASIN", "B0DK4Z4GPJ").strip().upper()
    if len(asin) != 10 or not asin.isalnum():
        raise ValueError("Invalid test ASIN")

    output = Path("v15-live-evidence")
    output.mkdir(parents=True, exist_ok=True)

    url = f"https://www.amazon.eg/dp/{asin}"

    with sync_playwright() as playwright:
        chrome = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
        )

        options = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }

        if chrome:
            options["executable_path"] = chrome

        browser = playwright.chromium.launch(**options)

        try:
            context = browser.new_context(
                locale="ar-EG",
                timezone_id="Africa/Cairo",
                user_agent=v14.UA,
                viewport={"width": 1440, "height": 1800},
                device_scale_factor=1,
            )

            page = context.new_page()

            try:
                # V15 only: retry once for a transient missing-price page.
                # Never retry an access challenge, login redirect or out-of-stock page.
                for attempt in range(2):
                    try:
                        observation = v14.inspect_amazon(page, url, asin)
                        break
                    except RuntimeError as error:
                        if str(error) != "no_live_price" or attempt == 1:
                            raise
                        try:
                            title = page.title().lower()
                            body = page.locator("body").inner_text(timeout=3000).lower()
                            current_url = page.url.lower()
                        except Exception:
                            # Unknown page state: do not retry blindly.
                            raise error
                        blocked = any(marker in title + body for marker in (
                            "captcha", "robot check", "enter the characters you see",
                        ))
                        unavailable = any(marker in body for marker in (
                            "currently unavailable", "temporarily out of stock",
                            "غير متوفر حالياً", "غير متوفر حاليًا",
                        ))
                        if blocked or "signin" in current_url or unavailable:
                            raise
                        print("V15_TRANSIENT_PRICE_RETRY", asin, flush=True)
                        page.close()
                        page = context.new_page()
            except Exception as probe_error:
                diagnostic = output / "amazon-failed-page.jpg"
                html = output / "amazon-failed-page.html"

                try:
                    page.screenshot(
                        path=str(diagnostic),
                        full_page=True,
                        type="jpeg",
                        quality=75,
                    )
                    html.write_text(
                        page.content(),
                        encoding="utf-8",
                    )
                    print("V15_FAILURE_EVIDENCE_SAVED")
                    print("PAGE_TITLE:", page.title())
                    print("PAGE_URL:", page.url)
                except Exception as diagnostic_error:
                    print(
                        "V15_DIAGNOSTIC_ERROR:",
                        str(diagnostic_error),
                    )

                if isinstance(probe_error, RuntimeError) and str(probe_error) == "no_live_price":
                    # Missing price is not evidence of a discount. Preserve diagnostics,
                    # release the lease with failure backoff, and continue next run.
                    github_output = os.environ.get("GITHUB_OUTPUT")
                    if not github_output:
                        raise RuntimeError("V15_GITHUB_OUTPUT_REQUIRED") from probe_error
                    with open(github_output, "a", encoding="utf-8") as stream:
                        stream.write("price_unavailable=true\n")
                    try:
                        title = page.title().lower()
                        body = page.locator("body").inner_text(timeout=5000).lower()
                        current_url = page.url.lower()
                        if any(x in title + body for x in ("captcha", "robot check", "enter the characters you see")):
                            reason = "ACCESS_CHALLENGE"
                        elif "signin" in current_url:
                            reason = "LOGIN_REDIRECT"
                        elif any(x in body for x in ("currently unavailable", "temporarily out of stock", "غير متوفر حالياً", "غير متوفر حاليًا")):
                            reason = "OUT_OF_STOCK"
                        elif not page.locator("#productTitle").count():
                            reason = "PRODUCT_PAGE_NOT_LOADED"
                        else:
                            reason = "PRICE_NOT_EXTRACTED"
                        print("V15_PRICE_FAILURE_REASON", asin, reason, flush=True)
                    except Exception as diagnosis_error:
                        print("V15_PRICE_FAILURE_REASON", asin, "DIAGNOSTIC_UNAVAILABLE", type(diagnosis_error).__name__, flush=True)
                    print("V15_PRICE_UNAVAILABLE", asin, flush=True)
                    return
                raise

            screenshot = output / "amazon-real-screenshot.jpg"

            v14.capture_product_screenshot(
                page,
                screenshot,
            )

            if not screenshot.is_file() or screenshot.stat().st_size == 0:
                raise RuntimeError("Screenshot missing or empty")

            image_hash = hashlib.sha256(
                screenshot.read_bytes()
            ).hexdigest()

            report = {
                "system": "Amazon V15",
                "mode": "isolated_live_probe",
                "asin": asin,
                "url": url,
                "captured_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "observation": observation,
                "screenshot": screenshot.name,
                "screenshot_sha256": image_hash,
                "telegram_sent": False,
                "production_queue_modified": False,
            }

            (output / "verification.json").write_text(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            print("V15_LIVE_PROBE_OK")
            print("ASIN:", asin)
            print("CURRENT_PRICE:", observation["current_price"])
            print("OLD_PRICE:", observation["old_price"])
            print("SCREENSHOT_SHA256:", image_hash)

        finally:
            browser.close()


if __name__ == "__main__":
    main()
