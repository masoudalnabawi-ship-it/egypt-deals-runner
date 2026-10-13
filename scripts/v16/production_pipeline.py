"""V16 guarded live pipeline: bounded probing, opt-in sends, machine-readable results."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_discovery import discover
from live_pipeline import probe_one
from screenshot_flash import send_flash


def run(send=False, max_candidates=5, discover_fn=discover, probe_fn=probe_one, alert_fn=send_flash):
    if not 1 <= max_candidates <= 10:
        raise ValueError('max_candidates must be 1..10')
    if send and os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') != '1':
        raise RuntimeError('Telegram send requires V16_PRIVATE_TELEGRAM_ENABLED=1')
    discovery = discover_fn(max_pages=4, max_candidates=max_candidates)
    result = {'discovered': len(discovery['candidates']), 'probed': 0,
              'eligible': 0, 'alerts': [], 'failures': [], 'discovery_errors': discovery['errors']}
    for item in discovery['candidates'][:max_candidates]:
        asin = item.get('asin')
        if not isinstance(asin, str) or len(asin) != 10 or not asin.isalnum():
            continue
        try:
            for observation, image, digest in probe_fn(asin):
                result['probed'] += 1
                try:
                    from screenshot_flash import candidate_from_observation
                    candidate = candidate_from_observation(observation)
                except ValueError:
                    result['failures'].append({'asin': asin, 'reason': 'INVALID_OFFER'})
                    continue
                if candidate is None:
                    continue
                result['eligible'] += 1
                # No message is sent in default dry-run mode.
                text_status = alert_fn(observation, enabled=send)
                result['alerts'].append({'asin': asin, 'kind': 'text', 'status': text_status})
                if send and text_status not in ('DISABLED', 'BELOW_THRESHOLD', 'MISSING_TELEGRAM_CONFIGURATION'):
                    photo_status = alert_fn(observation, screenshot_path=image,
                                            screenshot_sha256=digest, enabled=True)
                    result['alerts'].append({'asin': asin, 'kind': 'photo', 'status': photo_status})
        except Exception as exc:
            result['failures'].append({'asin': asin, 'reason': type(exc).__name__})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--send', action='store_true')
    p.add_argument('--max-candidates', type=int, default=5)
    p.add_argument('--output', default='v16-pipeline-report.json')
    args = p.parse_args()
    report = run(send=args.send, max_candidates=args.max_candidates)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('V16_PIPELINE_SUMMARY', json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
