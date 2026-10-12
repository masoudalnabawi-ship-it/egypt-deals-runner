"""Isolated sequential V15 batch: atomic leases, validated prices, per-ASIN recovery."""
import hashlib
import shutil
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from d1_monitoring_lease import claim_next_due, release_after_failure, release_after_success
from book_filter import classify, from_report
from d1_price_observation import prepare_observation
from flash_candidate import stage as stage_flash_candidate
from flash_private_alert import send as send_flash_alert
from flash_dedup import initialize as initialize_flash_dedup, send_once as send_flash_once
from private_price_review import review as review_price

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
        # Preserve genuine, SHA-256-verified evidence outside the temporary workspace.
        evidence_dir = ROOT / "v15-live-evidence" / asin
        evidence_dir.mkdir(parents=True, exist_ok=True)

        capture_id = report["captured_at"].replace(":", "-").replace("+", "_")
        saved_screenshot = evidence_dir / (capture_id + ".jpg")
        saved_verification = evidence_dir / (capture_id + ".json")

        shutil.copy2(screenshot, saved_screenshot)

        if hashlib.sha256(saved_screenshot.read_bytes()).hexdigest() != report["screenshot_sha256"]:
            saved_screenshot.unlink(missing_ok=True)
            raise RuntimeError("V15_PERSISTED_SCREENSHOT_HASH_MISMATCH")

        saved_report = dict(report)
        saved_report["screenshot"] = saved_screenshot.name

        saved_verification.write_text(
            json.dumps(saved_report, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print("V15_SCREENSHOT_PRESERVED", asin, saved_screenshot.name, flush=True)

        # Stage potential flash deal BEFORE D1 price persistence; never block monitoring.
        try:
            candidate_path = stage_flash_candidate(report, ROOT / 'v15-flash-candidates')
            if candidate_path:
                print('V15_FLASH_CANDIDATE', asin, 'UNVERIFIED', flush=True)
                try:
                    initialize_flash_dedup()
                    status = send_flash_once(json.loads(candidate_path.read_text(encoding='utf-8')), send_flash_alert)
                    print('V15_FLASH_PRIVATE_ALERT', asin, status, flush=True)
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
        try:
            status = review_price(report)
            print("V15_PRIVATE_PRICE_REVIEW", asin, status, flush=True)
        except Exception as exc:
            print("V15_PRIVATE_PRICE_REVIEW_FAILED", asin, type(exc).__name__, flush=True)

        return 'saved'


def main():
    count = int(os.environ.get('V15_BATCH_SIZE', '5'))
    if not 1 <= count <= 20:
        raise ValueError('V15_BATCH_SIZE must be 1..20')

    workers = int(os.environ.get("V15_BATCH_WORKERS", "4"))
    if not 1 <= workers <= 4:
        raise ValueError("V15_BATCH_WORKERS must be 1..4")

    leases = []
    for _ in range(count):
        lease = claim_next_due(lease_minutes=15)
        if lease is None:
            print("V15_BATCH_NO_MORE_DUE", flush=True)
            break
        leases.append(lease)
        print("V15_BATCH_CLAIM", lease["asin"], flush=True)

    def handle(lease):
        asin = lease["asin"]
        owner = lease["lease_owner"]
        priority = lease["priority"]
        persisted = False

        try:
            outcome = process(lease)
            persisted = outcome == "saved"

            if outcome in ("saved", "blocked"):
                release_after_success(asin, owner, priority)
                if outcome == "blocked":
                    from d1_monitoring_lease import query, quote
                    query(
                        "UPDATE product_monitoring SET "
                        "next_check_at=strftime('%Y-%m-%dT%H:%M:%S','now','+365 days') || '+00:00' "
                        "WHERE asin=" + quote(asin) + " AND lease_owner IS NULL;"
                    )
                    print("V15_BATCH_BOOK_SKIPPED", asin, flush=True)
                print("V15_BATCH_COMPLETE", asin, flush=True)
                return outcome

            release_after_failure(asin, owner)
            return "unavailable"

        except Exception as exc:
            print("V15_BATCH_PRODUCT_FAILED", asin, type(exc).__name__, flush=True)
            if not persisted:
                release_after_failure(asin, owner)
            else:
                raise
            return "failed"

    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(handle, lease) for lease in leases]
        for future in as_completed(futures):
            results.append(future.result())

    saved = results.count("saved")
    unavailable = results.count("unavailable")
    failed = results.count("failed")

    print(
        "V15_BATCH_SUMMARY",
        "saved=" + str(saved),
        "unavailable=" + str(unavailable),
        "failed=" + str(failed),
        flush=True
    )

    if failed and not saved and not unavailable:
        raise RuntimeError("V15_BATCH_ALL_PRODUCTS_FAILED")

if __name__ == '__main__':
    main()
