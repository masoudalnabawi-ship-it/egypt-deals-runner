"""V15 monitoring: claim before real probe; complete only after D1 price save.
No Telegram, no V14 or Noon changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from d1_monitoring_lease import claim, release_after_success
from d1_price_observation import prepare_observation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['claim', 'complete'])
    parser.add_argument('--asin', default=os.environ.get('V15_TEST_ASIN', 'B0DK4Z4GPJ'))
    args = parser.parse_args()
    asin = args.asin.strip().upper()
    if len(asin) != 10 or not asin.isalnum():
        raise ValueError('Invalid ASIN')

    if args.action == 'claim':
        lease = claim(asin, lease_minutes=30)
        output = os.environ.get('GITHUB_OUTPUT')
        if lease is None:
            print('V15_NO_DUE_PRODUCT')
            if output:
                with open(output, 'a', encoding='utf-8') as file:
                    file.write('claimed=false\n')
            return
        if not output:
            raise RuntimeError('GITHUB_OUTPUT required to securely pass lease owner')
        with open(output, 'a', encoding='utf-8') as file:
            file.write('claimed=true\n')
            file.write('owner=' + lease['lease_owner'] + '\n')
            file.write('priority=' + lease['priority'] + '\n')
        print('V15_MONITORING_CLAIM_OK', asin)
        return

    owner = os.environ.get('V15_LEASE_OWNER', '')
    priority = os.environ.get('V15_LEASE_PRIORITY', '')
    if not owner.startswith('v15-') or priority not in ('HOT', 'ACTIVE', 'STABLE', 'LOW'):
        raise RuntimeError('Missing or invalid lease metadata')
    evidence_dir = Path('v15-live-evidence')
    report_path = evidence_dir / 'verification.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    observation = prepare_observation(report_path)
    if report.get('asin') != asin or observation['asin'] != asin:
        raise RuntimeError('ASIN mismatch')
    screenshot = evidence_dir / report['screenshot']
    if not screenshot.is_file() or not screenshot.stat().st_size:
        raise RuntimeError('Missing screenshot')
    if hashlib.sha256(screenshot.read_bytes()).hexdigest() != report['screenshot_sha256']:
        raise RuntimeError('Screenshot checksum mismatch')
    # Called ONLY after the workflow's D1 save step has succeeded.
    next_due = release_after_success(asin, owner, priority)
    print('V15_MONITORING_CYCLE_COMPLETE', asin, next_due)


if __name__ == '__main__':
    main()
