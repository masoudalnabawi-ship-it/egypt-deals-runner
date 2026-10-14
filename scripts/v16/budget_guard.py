"""V16 budget admission guard. Persistent ledger is mandatory for scheduled runs.

The guard limits local admissions, NOT Cloudflare/GitHub billing. It never
claims to measure actual service usage. No network or Telegram side effects.
"""
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MONTHLY_RUNS = 240
DEFAULT_DAILY_RUNS = 12
DEFAULT_MAX_PROBES = 3


def _limit(name, default, maximum):
    raw = os.environ.get(name, str(default))
    if not raw.isdecimal() or not 1 <= int(raw) <= maximum:
        raise ValueError('INVALID_BUDGET_LIMIT:' + name)
    return int(raw)


def _path():
    raw = os.environ.get('V16_BUDGET_DB', '').strip()
    if not raw or not Path(raw).is_absolute():
        raise RuntimeError('V16_PERSISTENT_BUDGET_DB_REQUIRED')
    return Path(raw)


def max_probes():
    return _limit('V16_MAX_PROBES_PER_RUN', DEFAULT_MAX_PROBES, 10)


def claim_run(now=None):
    """Atomic admission. Fail closed when persistent ledger is unavailable.

    Caller must ensure V16_BUDGET_DB survives restarts; ephemeral Actions paths
    are NOT sufficient. Claim occurs before any browser/network activity.
    """
    now = time.time() if now is None else now
    dt = datetime.fromtimestamp(now, timezone.utc)
    month, day = dt.strftime('%Y-%m'), dt.strftime('%Y-%m-%d')
    db_path = _path()
    if not db_path.parent.is_dir():
        raise RuntimeError('V16_BUDGET_DIRECTORY_NOT_FOUND')
    daily = _limit('V16_DAILY_RUN_LIMIT', DEFAULT_DAILY_RUNS, 288)
    monthly = _limit('V16_MONTHLY_RUN_LIMIT', DEFAULT_MONTHLY_RUNS, 8928)
    with sqlite3.connect(str(db_path), timeout=15) as db:
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('CREATE TABLE IF NOT EXISTS run_budget (period TEXT PRIMARY KEY, used INTEGER NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        used_day = db.execute('SELECT used FROM run_budget WHERE period=?', ('D'+day,)).fetchone()
        used_month = db.execute('SELECT used FROM run_budget WHERE period=?', ('M'+month,)).fetchone()
        if (used_day and used_day[0] >= daily) or (used_month and used_month[0] >= monthly):
            return False
        for key in ('D'+day, 'M'+month):
            db.execute('INSERT INTO run_budget(period,used) VALUES(?,1) ON CONFLICT(period) DO UPDATE SET used=used+1', (key,))
        db.execute("DELETE FROM run_budget WHERE period LIKE 'D%' AND period < ?", ('D'+day[:4]+'-01',))
        db.execute("DELETE FROM run_budget WHERE period LIKE 'M%' AND period < ?", ('M'+str(int(month[:4])-1)+'-01',))
    return True
