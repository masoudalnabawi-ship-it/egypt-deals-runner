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
    if send and os.environ.get('V16_DEDUP_BACKEND') == 'd1':
        raise RuntimeError('V16_D1_REQUIRES_PROFESSIONAL_MODE')
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
    p.add_argument('--professional', action='store_true', help='One photo + caption per alert (V16 SQLite)')
    p.add_argument('--max-candidates', type=int, default=5)
    p.add_argument('--output', default='v16-pipeline-report.json')
    p.add_argument('--health-output', default='v16-health.json')
    args = p.parse_args()
    report = (run_professional(send=args.send, max_candidates=args.max_candidates)
              if args.professional else run(send=args.send, max_candidates=args.max_candidates))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    health = assess(report)
    save_health(args.health_output, health)
    print('V16_HEALTH', json.dumps(health, ensure_ascii=False))
    print('V16_PIPELINE_SUMMARY', json.dumps(report, ensure_ascii=False))


def run_professional(*, send=False, max_candidates=5,
                     discover_fn=discover, probe_fn=probe_one,
                     sender=None):
    """V16 photo + caption in one private message; SQLite dedup only."""
    from screenshot_flash import candidate_from_observation
    from smart_dedup import send_once, already_sent
    from professional_sender import send as professional_send

    if not 1 <= max_candidates <= 25:
        raise ValueError('max_candidates must be 1..25')

    if send and os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') != '1':
        raise RuntimeError('V16_PRIVATE_TELEGRAM_DISABLED')

    if send and os.environ.get('V16_DEDUP_BACKEND') not in ('sqlite','d1'):
        raise RuntimeError('V16_PROFESSIONAL_REQUIRES_DEDUP')
    max_sent = int(os.environ.get('V16_MAX_SEND_PER_RUN', '2'))
    min_discount = int(os.environ.get('V16_MIN_SEND_DISCOUNT', '50'))
    if not 1 <= max_sent <= 25 or not 5 <= min_discount <= 100:
        raise ValueError('INVALID_AUTOMATION_LIMITS')

    if send and os.environ.get('V16_DEDUP_BACKEND') == 'd1':
        from cloud_budget import claim_run
        if not claim_run():
            return {'discovered':0,'probed':0,'eligible':0,'alerts':[], 'failures':[], 'discovery_errors':[], 'budget':'DENIED'}
        from cloud_dedup import send_once, already_sent

    discovery = discover_fn(max_pages=8, max_candidates=150)
    print('V16_SOURCE_STATS', json.dumps(discovery.get('source_stats', []), ensure_ascii=False), flush=True)
    hints = [
        x['listing_discount_hint']
        for x in discovery['candidates']
        if x.get('listing_discount_hint') is not None
    ]
    print('V16_DISCOVERY_DISCOUNT_STATS', {
        'total': len(discovery['candidates']),
        'with_discount_hint': len(hints),
        'discount_50_plus': sum(x >= 50 for x in hints),
        'discount_90_plus': sum(x >= 90 for x in hints),
        'without_discount_hint': len(discovery['candidates']) - len(hints),
    }, flush=True)

    candidates = sorted(
        discovery['candidates'],
        key=lambda row: (
            row.get('listing_discount_hint') is None,
            -(row.get('listing_discount_hint') or 0),
        ),
    )

    result = {
        'discovered': len(candidates),
        'probed': 0,
        'eligible': 0,
        'alerts': [],
        'failures': [],
        'discovery_errors': discovery['errors'],
        'source_stats': discovery.get('source_stats', []),
    }

    sent_count = 0
    for item in candidates[:max_candidates]:
        if send and sent_count >= max_sent:
            break
        asin = item.get('asin')
        if not isinstance(asin, str) or len(asin) != 10 or not asin.isascii() or not asin.isalnum():
            continue

        probe = None
        try:
            probe = iter(probe_fn(asin))
            first = next(probe)
            observation = first[0]
            result['probed'] += 1

            candidate = candidate_from_observation(observation)
            print("V16_OFFER_DIAGNOSTIC", {
                "asin": asin,
                "price": observation.get("current_price"),
                "discount": observation.get("displayed_discount_pct"),
                "eligible": candidate is not None
            }, flush=True)
            if candidate is None:
                continue

            result['eligible'] += 1

            if send and float(candidate['displayed_discount_pct']) < min_discount:
                continue

            if not send:
                continue

            if already_sent(candidate):
                result['alerts'].append({
                    'asin': asin,
                    'kind': 'photo_with_caption',
                    'status': 'SKIPPED_DUPLICATE',
                })
                continue

            second = next(probe)
            image, digest = second[1], second[2]

            if not image or not digest:
                raise RuntimeError('SCREENSHOT_MISSING')

            candidate['screenshot_path'] = str(image)
            candidate['screenshot_sha256'] = digest

            status = send_once(
                candidate,
                sender or professional_send,
            )

            result['alerts'].append({
                'asin': asin,
                'kind': 'photo_with_caption',
                'status': status,
            })
            if status == 'SENT':
                sent_count += 1

        except StopIteration:
            result['failures'].append({
                'asin': asin,
                'reason': 'SCREENSHOT_NOT_PRODUCED',
            })
        except Exception as exc:
            result['failures'].append({
                'asin': asin,
                'reason': type(exc).__name__,
                'detail': str(exc)[:300],
            })
        finally:
            close = getattr(probe, 'close', None)
            if callable(close):
                close()

    return result


if __name__ == "__main__":
    main()
