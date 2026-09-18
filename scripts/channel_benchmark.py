#!/usr/bin/env python3

from urllib.request import Request, urlopen
from html import unescape
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".runtime_state"
STATE_FILE = STATE_DIR / "channel_benchmark.json"
NEW_FILE = STATE_DIR / "channel_new_posts.json"

CHANNELS = [
    "Yo_Ayman",
    "deals_me",
    "Sal7lyEgypt",
    "yahiaashry1",
    "WMTMSM6",
    "Deals3alMashy",
    "Mego_Reviews",
    "ba3bou3_deals",
    "Belnos",
    "OffersCommunityEG",
]

UA = "Mozilla/5.0"

def load_state():
    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {
            "initialized": False,
            "posts": {},
            "products": {},
        }

def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

def clean_text(s):
    s = re.sub(
        r"<br\s*/?>",
        "\n",
        s,
        flags=re.I,
    )
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def extract_price(text):
    patterns = [
        r"(?:ب|بسعر|السعر)\s*[:\-]?\s*([\d,]+(?:\.\d+)?)\s*(?:جنيه|ج\.?م)",
        r"([\d,]+(?:\.\d+)?)\s*(?:جنيه|ج\.?م)",
    ]

    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            try:
                return float(
                    m.group(1).replace(",", "")
                )
            except Exception:
                pass

    return 0.0

def extract_asin(text):
    patterns = [
        r"/(?:dp|gp/product)/([A-Z0-9]{10})",
        r"(?:amazon[^/\s]*/)([A-Z0-9]{10})(?:\b|/)",
        r"\b(B0[A-Z0-9]{8})\b",
    ]

    for pat in patterns:
        m = re.search(
            pat,
            text,
            flags=re.I,
        )
        if m:
            return m.group(1).upper()

    return ""

def fetch_channel(ch):
    req = Request(
        f"https://t.me/s/{ch}",
        headers={"User-Agent": UA},
    )

    with urlopen(req, timeout=12) as r:
        page = r.read().decode(
            "utf-8",
            errors="ignore",
        )

    blocks = re.findall(
        r'(<div class="tgme_widget_message[^>]*'
        r'data-post="' + re.escape(ch) +
        r'/\d+".*?</div>\s*</div>\s*</div>)',
        page,
        flags=re.S,
    )

    out = []

    for block in blocks:
        post = re.search(
            r'data-post="([^"]+)"',
            block,
        )

        if not post:
            continue

        dt = re.search(
            r'<time[^>]*datetime="([^"]+)"',
            block,
        )

        txt = ""
        m = re.search(
            r'<div class="tgme_widget_message_text'
            r'[^>]*>(.*?)</div>',
            block,
            flags=re.S,
        )

        if m:
            txt = clean_text(m.group(1))

        links = [
            unescape(x)
            for x in re.findall(
                r'href="(https?://[^"]+)"',
                block,
            )
            if "t.me/" not in x
        ]

        joined = txt + " " + " ".join(links)

        out.append({
            "post": post.group(1),
            "channel": ch,
            "time": (
                dt.group(1)
                if dt
                else ""
            ),
            "text": txt,
            "links": links,
            "price": extract_price(txt),
            "asin": extract_asin(joined),
        })

    return out


def fetch_channel_safe(ch):
    try:
        return ch, fetch_channel(ch), None
    except Exception as exc:
        return ch, [], exc

def main():
    state = load_state()

    first_run = not bool(
        state.get("initialized")
    )

    known = state.setdefault(
        "posts",
        {},
    )

    new_posts = []

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(
            pool.map(
                fetch_channel_safe,
                CHANNELS,
            )
        )

    for ch, posts, error in results:
        channel_has_history = any(
            str(k).lower().startswith(
                ch.lower() + "/"
            )
            for k in known
        )

        if error is not None:
            print(
                f"❌ CHANNEL {ch} "
                f"| {repr(error)}"
            )
            continue

        print(
            f"✅ CHANNEL {ch} "
            f"| posts={len(posts)}"
        )

        for p in posts:
            key = p["post"]

            if key in known:
                continue

            known[key] = {
                **p,
                "first_observed_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
            }

            if not first_run and channel_has_history:
                new_posts.append(p)

    state["initialized"] = True
    state["updated_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    # Keep recent benchmark history bounded.
    if len(known) > 3000:
        items = list(known.items())
        state["posts"] = dict(
            items[-3000:]
        )

    save_state(state)

    NEW_FILE.write_text(
        json.dumps(
            new_posts,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"📥 CHANNEL NEW FILE | posts={len(new_posts)}"
    )

    if first_run:
        print(
            "✅ BENCHMARK BASELINE CREATED "
            f"| stored={len(state['posts'])}"
        )
        print(
            "ℹ️ Existing messages were NOT treated "
            "as new deals."
        )
        return

    print(
        f"🆕 NEW BENCHMARK POSTS = "
        f"{len(new_posts)}"
    )

    for p in new_posts:
        print(
            "BENCHMARK NEW"
            f" | {p['post']}"
            f" | price={p['price']}"
            f" | asin={p['asin'] or '-'}"
            f" | {p['text'][:100]}"
        )

if __name__ == "__main__":
    main()
