"""V16 phase 6: bounded local report runner. No scraping or scheduled monitoring.

Default is dry-run. Real Telegram sending requires BOTH --send and opt-in env,
existing V15 Telegram secrets, and working persistent D1 dedup.
"""
import argparse
import json
from pathlib import Path
from verified_alert_bridge import from_verified_report


def run(report, *, send=False, transport=None):
    decision = from_verified_report(report)
    alert = decision['private_alert']
    if alert is None:
        return {'status': 'BELOW_THRESHOLD', 'score': decision['score']}
    if not send:
        return {'status': 'DRY_RUN', 'tier': alert['tier'], 'score': decision['score']}
    if transport is None:
        from private_telegram_transport import send_verified_private
        transport = send_verified_private
    status = transport(report, enabled=True)
    return {'status': status, 'tier': alert['tier'], 'score': decision['score']}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, help='Existing verified report JSON')
    parser.add_argument('--send', action='store_true', help='Explicitly opt into private sending')
    args = parser.parse_args(argv)
    path = Path(args.report)
    if not path.is_file() or path.stat().st_size > 1_000_000:
        parser.error('Report missing or too large')
    report = json.loads(path.read_text(encoding='utf-8'))
    result = run(report, send=args.send)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result['status'] in ('MISSING_TELEGRAM_CONFIGURATION', 'SEND_FAILED_RETRY_LATER', 'SCREENSHOT_RETRY_LATER'):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
