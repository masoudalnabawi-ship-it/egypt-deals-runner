#!/usr/bin/env python3

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
import html
import json
import re
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".runtime_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / "amazon_native_scout.json"

WATCH_FILES = [
    STATE_DIR / "amazon_manual_watch.txt",
    ROOT
    / "amazon_dynamic_runtime_v8"
    / "telegram_deals_bot_v1_ready"
    / ".amazon_manual_watch.txt",
]

BASE = "https://www.amazon.eg"

ROOT_URLS = [
    BASE + "/gp/bestsellers",
    BASE + "/gp/new-releases",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
}

ASIN_RE = re.compile(
    r'data-asin=["\']([A-Z0-9]{10})'
)

HREF_RE = re.compile(
    r'href=["\']([^"\']+)["\']'
)


def log(msg):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "|",
        msg,
        flush=True,
    )


def load_state():
    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {
        "known": [],
        "backlog": [],
        "categories": [],
        "cursor": 0,
    }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch(url):
    req = urllib.request.Request(
        url,
        headers=HEADERS,
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=18,
        ) as r:
            if r.status != 200:
                return url, ""

            body = r.read().decode(
                "utf-8",
                errors="ignore",
            )

            return url, body

    except Exception as exc:
        log(
            f"⚠️ NATIVE FETCH FAILED"
            f" | {url}"
            f" | {type(exc).__name__}"
        )
        return url, ""


def extract_asins(body):
    return set(
        ASIN_RE.findall(
            body or ""
        )
    )


def extract_category_urls(body):
    out = []

    for href in HREF_RE.findall(
        body or ""
    ):
        href = html.unescape(href)

        url = urljoin(
            BASE,
            href,
        ).split("#")[0]

        if (
            "/gp/bestsellers/" not in url
            and "/gp/new-releases/" not in url
        ):
            continue

        if url not in out:
            out.append(url)

    return out


def add_watch_asin(asin):
    asin = str(asin).strip().upper()

    if not re.fullmatch(
        r"[A-Z0-9]{10}",
        asin,
    ):
        return False

    added = False

    for path in WATCH_FILES:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        existing = []

        if path.exists():
            existing = [
                x.strip().upper()
                for x in path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if x.strip()
            ]

        if asin not in set(existing):
            existing.append(asin)

            path.write_text(
                "\n".join(existing) + "\n",
                encoding="utf-8",
            )

            added = True

    return added


def scan_cycle(state):
    known = set(
        str(x).upper()
        for x in state.get(
            "known",
            [],
        )
    )

    backlog = [
        str(x).upper()
        for x in state.get(
            "backlog",
            [],
        )
    ]

    categories = list(
        state.get(
            "categories",
            [],
        )
    )

    cursor = int(
        state.get(
            "cursor",
            0,
        )
        or 0
    )

    discovered = set()

    # Always refresh root native Amazon pages.
    root_bodies = []

    with ThreadPoolExecutor(
        max_workers=2
    ) as pool:
        futures = [
            pool.submit(fetch, url)
            for url in ROOT_URLS
        ]

        for future in as_completed(
            futures
        ):
            _, body = future.result()

            if not body:
                continue

            root_bodies.append(body)

            discovered.update(
                extract_asins(body)
            )

    # Refresh available category URLs.
    fresh_categories = []

    for body in root_bodies:
        fresh_categories.extend(
            extract_category_urls(body)
        )

    for url in fresh_categories:
        if url not in categories:
            categories.append(url)

    initialized = bool(
        state.get("initialized", False)
    )

    baseline_scanned = set(
        str(x)
        for x in state.get(
            "baseline_scanned_categories",
            [],
        )
        if x
    )

    # During first startup, learn ALL native categories
    # gradually without feeding anything to Fast Lane.
    batch = []

    if not initialized:
        pending = [
            url
            for url in categories
            if url not in baseline_scanned
        ]

        batch = pending[:6]

    elif categories:
        count = min(
            6,
            len(categories),
        )

        for i in range(count):
            batch.append(
                categories[
                    (cursor + i)
                    % len(categories)
                ]
            )

        cursor = (
            cursor + count
        ) % len(categories)

    if batch:
        with ThreadPoolExecutor(
            max_workers=3
        ) as pool:
            futures = [
                pool.submit(fetch, url)
                for url in batch
            ]

            for future in as_completed(
                futures
            ):
                _, body = future.result()

                if body:
                    discovered.update(
                        extract_asins(body)
                    )

    if not initialized:
        baseline_scanned.update(batch)

        known.update(discovered)
        backlog = []

        remaining = [
            url
            for url in categories
            if url not in baseline_scanned
        ]

        state["baseline_scanned_categories"] = sorted(
            baseline_scanned
        )

        if categories and not remaining:
            state["initialized"] = True
            state["baseline_completed_at"] = int(
                time.time()
            )

            # Seed the existing Amazon universe gradually.
            # This lets the radar verify current discounts
            # without flooding direct product pages.
            backlog = sorted(
                set(backlog) | known
            )

            log(
                "✅ AMAZON NATIVE BASELINE COMPLETE"
                f" | categories={len(categories)}"
                f" | known={len(known)}"
                f" | seed_backlog={len(backlog)}"
            )

        else:
            log(
                "🌱 AMAZON NATIVE BASELINE WARMING"
                f" | scanned={len(baseline_scanned)}"
                f" | remaining={len(remaining)}"
                f" | known={len(known)}"
            )

        new_asins = []

    else:
        new_asins = sorted(
            discovered - known
        )

        if new_asins:
            log(
                "🆕 AMAZON NATIVE DISCOVERED"
                f" | new={len(new_asins)}"
                f" | total_scan={len(discovered)}"
            )

            for asin in new_asins:
                if asin not in backlog:
                    backlog.append(asin)

            known.update(
                new_asins
            )

    # Feed Fast Lane gradually so Amazon is not flooded.
    # Keep product-page verification gentle:
    # max 8 ASINs are handed to the existing radar per cycle.
    feed_count = min(
        8,
        len(backlog),
    )

    fed = 0

    for _ in range(feed_count):
        asin = backlog.pop(0)

        if add_watch_asin(asin):
            fed += 1

            log(
                "⚡ AMAZON NATIVE -> FAST LANE"
                f" | {asin}"
            )

    state["known"] = sorted(
        known
    )

    state["backlog"] = backlog
    state["categories"] = categories
    state["cursor"] = cursor
    state["last_scan_at"] = int(
        time.time()
    )
    state["last_scan_asins"] = len(
        discovered
    )
    state["last_fed"] = fed

    save_state(state)

    log(
        "✅ AMAZON NATIVE SCAN"
        f" | discovered={len(discovered)}"
        f" | known={len(known)}"
        f" | backlog={len(backlog)}"
        f" | fed={fed}"
        f" | categories={len(categories)}"
    )


def main():
    log(
        "🚀 AMAZON NATIVE SCOUT ONLINE"
    )

    state = load_state()

    while True:
        try:
            scan_cycle(state)

        except Exception as exc:
            log(
                "❌ AMAZON NATIVE SCOUT ERROR"
                f" | {repr(exc)}"
            )

        time.sleep(30)


if __name__ == "__main__":
    main()
