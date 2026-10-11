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

            observation = v14.inspect_amazon(
                page,
                url,
                asin,
            )

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
