"""V16 Telegram update ledger. No network or public publishing."""
import time

from review_store import connect

LEASE_SECONDS = 120


def claim_update(update_id):
    """Claim an update, allowing retries after an expired lease."""
    if type(update_id) is not int or update_id < 0:
        raise ValueError('INVALID_UPDATE_ID')

    now = time.time()

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_updates (
            update_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at REAL NOT NULL
        )''')

        db.execute('BEGIN IMMEDIATE')

        row = db.execute(
            'SELECT state, updated_at FROM review_updates WHERE update_id=?',
            (update_id,),
        ).fetchone()

        if row:
            state, updated_at = row

            if state == 'done':
                return False

            if state == 'processing' and now - updated_at < LEASE_SECONDS:
                return False

        db.execute(
            '''INSERT INTO review_updates(update_id,state,updated_at)
               VALUES (?, 'processing', ?)
               ON CONFLICT(update_id) DO UPDATE SET
               state='processing', updated_at=excluded.updated_at''',
            (update_id, now),
        )

    return True


def finish_update(update_id):
    """Mark a successfully processed update as completed."""
    with connect() as db:
        cursor = db.execute(
            """UPDATE review_updates SET state='done',updated_at=?
               WHERE update_id=? AND state='processing'""",
            (time.time(), update_id),
        )
        return cursor.rowcount == 1


def release_update(update_id):
    """Allow an unsuccessful update to be retried."""
    with connect() as db:
        db.execute(
            "DELETE FROM review_updates WHERE update_id=? AND state='processing'",
            (update_id,),
        )
