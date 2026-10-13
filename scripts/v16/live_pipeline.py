"""Bounded opt-in V16 discovery -> product inspection -> private screenshot alert.

Uses V15 read-only product probe, never V15's queue or batch monitoring.
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


def probe_one(asin, *, runner=subprocess.run):
    with tempfile.TemporaryDirectory(prefix='v16-probe-') as tmp:
        work = Path(tmp)
        env = dict(os.environ, V15_TEST_ASIN=asin, GITHUB_OUTPUT=str(work / 'output.txt'))
        runner([sys.executable, str(ROOT / 'scripts/v15/live_probe.py')],
               cwd=work, env=env, check=True, timeout=115)
        report_path = work / 'v15-live-evidence/verification.json'
        if not report_path.is_file():
            return None
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('asin') != asin:
            raise ValueError('REPORT_ASIN_MISMATCH')
        image_name = report.get('screenshot', '')
        if not image_name or Path(image_name).name != image_name:
            raise ValueError('INVALID_SCREENSHOT_PATH')
        image = report_path.parent / image_name
        if not image.is_file():
            raise ValueError('SCREENSHOT_MISSING')
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != report.get('screenshot_sha256'):
            raise ValueError('SCREENSHOT_HASH_MISMATCH')
        yield observation_from_report(report), image, digest


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
                # Send the text notification before the photo. This cannot make
                # the alert earlier than the product probe; it does prevent
                # screenshot uploading from delaying the initial notification.
                text_status = alert_fn(observation, enabled=send)
                summary['alerts'].append({'asin': asin, 'status': text_status,
                                          'kind': 'text'})
                if send and text_status not in ('DISABLED', 'BELOW_THRESHOLD',
                                                'MISSING_TELEGRAM_CONFIGURATION'):
                    photo_status = alert_fn(observation, screenshot_path=image,
                                            screenshot_sha256=digest, enabled=send)
                    summary['alerts'].append({'asin': asin, 'status': photo_status,
                                              'kind': 'photo'})
        except Exception as exc:
            summary['failures'] += 1
            print('V16_PRODUCT_FAILED', asin, type(exc).__name__, flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true', help='Send to private Telegram; requires V16_PRIVATE_TELEGRAM_ENABLED=1 and V15 credentials')
    parser.add_argument('--max-candidates', type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_pipeline(send=args.send, max_candidates=args.max_candidates), ensure_ascii=False))


if __name__ == '__main__':
    main()
