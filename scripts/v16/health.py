"""Local V16 run health: JSON snapshots, safe atomic writes, no credentials."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def assess(report, *, minimum_discovered=1):
    discovered = int(report.get('discovered', 0))
    probed = int(report.get('probed', 0))
    failures = len(report.get('failures', []))
    errors = len(report.get('discovery_errors', []))
    alerts = report.get('alerts', [])
    successful = sum(1 for x in alerts if x.get('kind') == 'text' and
                     x.get('status') not in ('DISABLED', 'BELOW_THRESHOLD',
                                             'MISSING_TELEGRAM_CONFIGURATION',
                                             'ERROR', 'FAILED'))
    if discovered < minimum_discovered:
        status = 'NO_CANDIDATES'
    elif probed == 0:
        status = 'NO_VERIFIED_PROBES'
    elif failures:
        status = 'PARTIAL_FAILURE'
    else:
        status = 'OK'
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'status': status, 'discovered': discovered, 'probed': probed,
            'eligible': int(report.get('eligible', 0)),
            'text_alert_results': successful,
            'product_failures': failures, 'source_failures': errors}


def save_health(path, health):
    """Atomically save diagnostics without storing Telegram tokens or product PII."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.v16-health-', dir=str(dest.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(health, out, ensure_ascii=False, indent=2)
            out.write('\n')
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
