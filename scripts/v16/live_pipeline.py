"""Bounded opt-in V16 discovery -> product inspection -> private screenshot alert.

Uses the V16 fast probe with V14 read-only inspector; no V15 dependency.
Default is dry-run. No D1 writes unless --send is explicitly enabled.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V16 = Path(__file__).resolve().parent
sys.path.insert(0, str(V16))
from live_discovery import discover
from screenshot_flash import send_flash


def observation_from_report(report):
    obs = report.get('observation') or {}
    asin = report.get('asin')
    if not isinstance(obs, dict) or obs.get('page_asin') != asin:
        raise ValueError('PAGE_ASIN_MISMATCH')
    return {'asin': asin, 'title': obs.get('title'),
            'current_price': obs.get('current_price'),
            'displayed_discount_pct': obs.get('savings_percent')}


def probe_one(asin, *, runner=None):
    """V16 read-only probe; V14 inspector remains the supported page parser.

    runner is accepted for compatibility but no V15 subprocess is invoked.
    """
    from fast_probe import probe_fast
    for observation, image, digest in probe_fast(asin):
        if image is not None:
            yield observation, image, digest


def run_pipeline(*, send=False, max_candidates=5, discover_fn=discover,
                 probe_fn=probe_one, alert_fn=send_flash):
    if not 1 <= max_candidates <= 10:
        raise ValueError('max_candidates must be 1..10')
    found = discover_fn(max_pages=2, max_candidates=max_candidates)
    summary = {'discovered': len(found), 'probed': 0, 'alerts': [], 'failures': 0}
    for item in found[:max_candidates]:
        asin = item.get('asin', '')
        if not isinstance(asin, str) or len(asin) != 10 or not asin.isalnum():
            continue
        try:
            for observation, image, digest in probe_fn(asin):
                summary['probed'] += 1
                result = alert_fn(observation, screenshot_path=image,
                                  screenshot_sha256=digest, enabled=send)
                summary['alerts'].append({'asin': asin, 'status': result})
        except Exception as exc:
            summary['failures'] += 1
            print('V16_PRODUCT_FAILED', asin, type(exc).__name__, flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true', help='Send to private Telegram; requires explicit private Telegram opt-in')
    parser.add_argument('--max-candidates', type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_pipeline(send=args.send, max_candidates=args.max_candidates), ensure_ascii=False))


if __name__ == '__main__':
    main()
