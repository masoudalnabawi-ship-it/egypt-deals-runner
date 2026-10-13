"""V16 guarded live pipeline: bounded probing, opt-in sends, machine-readable results."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_discovery import discover
from fast_probe import probe_fast as probe_one
from screenshot_flash import send_flash
from health import assess, save_health


def run(send=False, max_candidates=5, discover_fn=discover, probe_fn=probe_one, alert_fn=send_flash):
    if not 1 <= max_candidates <= 10:
        raise ValueError('max_candidates must be 1..10')
    if send and os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') != '1':
        raise RuntimeError('Telegram send requires V16_PRIVATE_TELEGRAM_ENABLED=1')
    # Collect a larger pool; probe only the strongest candidates.
    discovery = discover_fn(max_pages=4, max_candidates=100)
    candidates = sorted(discovery['candidates'], key=lambda row: (
        row.get('listing_discount_hint') is None,
        -(row.get('listing_discount_hint') or 0),
    ))
    result = {'discovered': len(candidates), 'probed': 0,
              'eligible': 0, 'alerts': [], 'failures': [], 'discovery_errors': discovery['errors']}
    for item in candidates[:max_candidates]:
        asin = item.get('asin')
        if not isinstance(asin, str) or len(asin) != 10 or not asin.isascii() or not asin.isalnum():
            continue
        text_status = None
        eligible = False
        probe = None
        try:
            probe = iter(probe_fn(asin))
            for observation, image, digest in probe:
                if image is None:
                    result['probed'] += 1
                    try:
                        from screenshot_flash import candidate_from_observation
                        eligible = candidate_from_observation(observation) is not None
                    except ValueError:
                        result['failures'].append({'asin': asin, 'reason': 'INVALID_OFFER'})
                        continue
                    if not eligible:
                        break
                    result['eligible'] += 1
                    text_status = alert_fn(observation, enabled=send)
                    result['alerts'].append({'asin': asin, 'kind': 'text', 'status': text_status})
                    # Screenshot only after a successfully delivered text alert.
                    if not send or text_status not in ('SENT', 'SENT_NEW', 'SENT_UPDATED'):
                        break
                elif eligible and send and text_status in ('SENT', 'SENT_NEW', 'SENT_UPDATED'):
                    try:
                        photo_status = alert_fn(observation, screenshot_path=image,
                                                screenshot_sha256=digest, enabled=True)
                        result['alerts'].append({'asin': asin, 'kind': 'photo', 'status': photo_status})
                    except Exception as exc:
                        result['failures'].append({'asin': asin, 'reason': 'PHOTO_' + type(exc).__name__, 'detail': str(exc)[:300]})
        except Exception as exc:
            result['failures'].append({'asin': asin, 'reason': type(exc).__name__, 'detail': str(exc)[:300]})
        finally:
            close = getattr(probe, 'close', None)
            if callable(close):
                close()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--send', action='store_true')
    p.add_argument('--max-candidates', type=int, default=5)
    p.add_argument('--output', default='v16-pipeline-report.json')
    p.add_argument('--health-output', default='v16-health.json')
    args = p.parse_args()
    report = run(send=args.send, max_candidates=args.max_candidates)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    health = assess(report)
    save_health(args.health_output, health)
    print('V16_HEALTH', json.dumps(health, ensure_ascii=False))
    print('V16_PIPELINE_SUMMARY', json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
