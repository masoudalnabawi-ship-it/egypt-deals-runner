#!/usr/bin/env python3

from urllib.request import Request, urlopen
from urllib.parse import unquote, urlsplit
import re


UA = "Mozilla/5.0"


def extract_asin(value):
    value = unquote(str(value or ""))

    patterns = [
        r"ASIN\.1=([A-Z0-9]{10})",
        r"/(?:dp|gp/product)/([A-Z0-9]{10})",
        r"\b(B0[A-Z0-9]{8})\b",
    ]

    for pat in patterns:
        m = re.search(
            pat,
            value,
            flags=re.I,
        )
        if m:
            return m.group(1).upper()

    return ""


def simple_resolve(url):
    try:
        req = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept-Language":
                    "ar-EG,ar;q=0.9,en;q=0.8",
            },
        )

        with urlopen(req, timeout=20) as r:
            return r.geturl()

    except Exception:
        return ""


def browser_resolve(url, browser):
    page = browser.new_page(
        user_agent=UA
    )

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=45000,
        )

        page.wait_for_timeout(4500)

        return page.url

    except Exception:
        return ""

    finally:
        page.close()


def resolve_one(url, browser=None):
    original = str(url or "").strip()

    if not original:
        return {
            "original_url": "",
            "final_url": "",
            "asin": "",
            "store": "",
        }

    # Direct ASIN already present.
    asin = extract_asin(original)

    if asin:
        return {
            "original_url": original,
            "final_url": original,
            "asin": asin,
            "store": "amazon",
        }

    final = simple_resolve(original)

    asin = extract_asin(final)

    # Affiliate/redirect links may reveal Amazon only
    # after browser-side navigation.
    origin_host = urlsplit(
        original
    ).netloc.lower()

    final_host = urlsplit(
        final
    ).netloc.lower() if final else ""

    redirect_hosts = (
        "3rrood.com",
        "link.amazon",
        "bit.ly",
        "cutt.ly",
        "tinyurl.com",
        "rb.gy",
        "shorturl",
    )

    needs_browser = (
        not asin
        and browser is not None
        and (
            "/ax/claim" in final.lower()
            or any(
                host in origin_host
                for host in redirect_hosts
            )
            or any(
                host in final_host
                for host in redirect_hosts
            )
        )
    )

    if (
        not asin
        and needs_browser
        and browser is not None
    ):
        browser_final = browser_resolve(
            original,
            browser,
        )

        if browser_final:
            final = browser_final
            asin = extract_asin(final)

    low = final.lower()

    if (
        "amazon.eg" in low
        or "amazon." in low
        or "link.amazon" in original.lower()
    ):
        store = "amazon"

    elif "noon." in low or "noon." in original.lower():
        store = "noon"

    elif "jumia." in low or "jumia." in original.lower():
        store = "jumia"

    else:
        store = ""

    return {
        "original_url": original,
        "final_url": final,
        "asin": asin,
        "store": store,
    }


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    tests = [
        "https://link.amazon/B07Pmot0B",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        for url in tests:
            result = resolve_one(
                url,
                browser,
            )

            print("ORIGINAL:", result["original_url"])
            print("FINAL   :", result["final_url"][:250])
            print("STORE   :", result["store"] or "-")
            print("ASIN    :", result["asin"] or "-")
            print("---")

        browser.close()
