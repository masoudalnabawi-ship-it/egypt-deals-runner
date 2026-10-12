"""Isolated sequential V15 batch: atomic leases, validated prices, per-ASIN recovery."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from d1_monitoring_lease import claim_next_due, release_after_failure, release_after_success
from book_filter import classify, from_report
from d1_price_observation import prepare_observation
from flash_candidate import stage as stage_flash_candidate
from flash_private_alert import send as send_flash_alert

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / 'scripts/v15/live_probe.py'
EVIDENCE = ROOT / 'scripts/v15/evidence_pipeline.py'
DATABASE = 'egypt-amazon-v15-db'


def run(command, cwd, env=None, timeout=120):
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=timeout)


def process(lease):
    asin, owner, priority = lease['asin'], lease['lease_owner'], lease['priority']
    reason = classify(asin=asin)
    if reason:
        print('V15_BOOK_FILTER_BLOCKED', asin, reason, flush=True)
        return 'blocked'
    # One isolated workspace per product prevents stale verification.json reuse.
    with tempfile.TemporaryDirectory(prefix='v15-batch-') as work:
        work = Path(work)
        output = work / 'probe-output'
        env = os.environ.copy()
        env['V15_TEST_ASIN'] = asin
        env['GITHUB_OUTPUT'] = str(output)
        run([sys.executable, str(PROBE)], work, env, timeout=105)
        flags = dict(line.split('=', 1) for line in output.read_text().splitlines()
                     if '=' in line) if output.exists() else {}
        if flags.get('price_unavailable') == 'true':
            print('V15_BATCH_PRICE_UNAVAILABLE', asin, flush=True)
            return 'unavailable'
        verification = work / 'v15-live-evidence/verification.json'
        if not verification.is_file():
            raise RuntimeError('V15_BATCH_MISSING_VERIFICATION')
        report = json.loads(verification.read_text(encoding='utf-8'))
        if report.get('asin') != asin:
            raise RuntimeError('V15_BATCH_REPORT_ASIN_MISMATCH')
        reason = from_report(report)
        if reason:
            print('V15_BOOK_FILTER_BLOCKED', asin, reason, flush=True)
            return 'blocked'
        screenshot_name = report.get('screenshot', '')
        screenshot = verification.parent / screenshot_name
        if not screenshot_name or Path(screenshot_name).name != screenshot_name or not screenshot.is_file():
            raise RuntimeError('V15_BATCH_SCREENSHOT_MISSING')
        if hashlib.sha256(screenshot.read_bytes()).hexdigest() != report.get('screenshot_sha256'):
            raise RuntimeError('V15_BATCH_SCREENSHOT_HASH_MISMATCH')
        # Stage potential flash deal BEFORE D1 price persistence; never block monitoring.
        try:
            candidate_path = stage_flash_candidate(report, ROOT / 'v15-flash-candidates')
            if candidate_path:
                print('V15_FLASH_CANDIDATE', asin, 'UNVERIFIED', flush=True)
                try:
                    delivered = send_flash_alert(json.loads(candidate_path.read_text(encoding='utf-8')))
                    print('V15_FLASH_PRIVATE_ALERT', asin, 'SENT' if delivered else 'NOT_CONFIGURED', flush=True)
                except Exception as alert_exc:
                    print('V15_FLASH_PRIVATE_ALERT_FAILED', asin, type(alert_exc).__name__, flush=True)
        except Exception as flash_exc:
            print('V15_FLASH_STAGING_FAILED', asin, type(flash_exc).__name__, flush=True)
        run([sys.executable, str(EVIDENCE), str(verification)], work, timeout=30)
        # prepare_observation validates the report and creates SQL without editing V14.
        observation = prepare_observation(verification)
        if observation['asin'] != asin:
            raise RuntimeError('V15_BATCH_ASIN_MISMATCH')
        sql = work / 'price-observation.sql'
        run([sys.executable, str(ROOT / 'scripts/v15/d1_price_observation.py'),
             str(verification), str(sql)], work, timeout=30)
        if not sql.is_file() or not sql.stat().st_size:
            raise RuntimeError('V15_BATCH_SQL_MISSING')
        run(['npx', '--yes', 'wrangler@4.149.0', 'd1', 'execute', DATABASE,
             '--remote', '--file', str(sql)], ROOT, timeout=90)
        print('V15_BATCH_PRICE_SAVED', asin, flush=True)
        return 'saved'


def main():
    count = int(os.environ.get('V15_BATCH_SIZE', '5'))
    if not 1 <= count <= 5:
        raise ValueError('V15_BATCH_SIZE must be 1..5')
    saved = unavailable = failed = 0
    for _ in range(count):
        # An infrastructure failure during claiming is not silently treated as no work.
        lease = claim_next_due(lease_minutes=15)
        if lease is None:
            print('V15_BATCH_NO_MORE_DUE', flush=True)
            break
        asin, owner, priority = lease['asin'], lease['lease_owner'], lease['priority']
        print('V15_BATCH_CLAIM', asin, flush=True)
        persisted = False
        try:
            outcome = process(lease)
            persisted = outcome == 'saved'
            if outcome in ('saved', 'blocked'):
                release_after_success(asin, owner, priority)
                if outcome == 'saved':
                    saved += 1
                else:
                    print('V15_BATCH_BOOK_SKIPPED', asin, flush=True)
                if outcome == 'blocked':
                    from d1_monitoring_lease import query, quote
                    query("UPDATE product_monitoring SET next_check_at=strftime('%Y-%m-%dT%H:%M:%S','now','+365 days') || '+00:00' WHERE asin=" + quote(asin) + " AND lease_owner IS NULL;")
                print('V15_BATCH_COMPLETE', asin, flush=True)
            else:
                release_after_failure(asin, owner)
                unavailable += 1
        except Exception as exc:
            failed += 1
            print('V15_BATCH_PRODUCT_FAILED', asin, type(exc).__name__, flush=True)
            # If release fails, abort: an orphaned lease needs operator attention.
            if not persisted:
                release_after_failure(asin, owner)
            else:
                raise
    print('V15_BATCH_SUMMARY', 'saved='+str(saved),
          'unavailable='+str(unavailable), 'failed='+str(failed), flush=True)
    # Product-level failures are isolated; an all-failed batch needs investigation.
    if failed and not saved and not unavailable:
        raise RuntimeError('V15_BATCH_ALL_PRODUCTS_FAILED')


if __name__ == '__main__':
    main()
