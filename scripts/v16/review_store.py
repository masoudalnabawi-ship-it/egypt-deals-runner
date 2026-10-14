"""V16 private review state storage. No Telegram or public publishing."""
import sqlite3
import time

from smart_dedup import database_path, validate

VALID_STATES = {'pending', 'rejected', 'editing', 'custom'}


def connect():
    db = sqlite3.connect(str(database_path()), timeout=20)
    db.execute('PRAGMA busy_timeout=20000')
    db.execute('''CREATE TABLE IF NOT EXISTS review_states (
        asin TEXT PRIMARY KEY,
        state TEXT NOT NULL,
        updated_at REAL NOT NULL
    )''')
    return db


def set_state(asin, state):
    if state not in VALID_STATES:
        raise ValueError('INVALID_REVIEW_STATE')

    validate({'asin': asin, 'current_price': '1'})

    with connect() as db:
        db.execute(
            '''INSERT INTO review_states (asin,state,updated_at)
               VALUES (?,?,?)
               ON CONFLICT(asin) DO UPDATE SET
               state=excluded.state,
               updated_at=excluded.updated_at''',
            (asin, state, time.time()),
        )

    return state


def get_state(asin):
    validate({'asin': asin, 'current_price': '1'})

    with connect() as db:
        row = db.execute(
            'SELECT state FROM review_states WHERE asin=?',
            (asin,),
        ).fetchone()

    return row[0] if row else None


def save_message(asin, message):
    """Save an admin-authored message for a reviewed offer."""
    from message_validation import validate_message

    validate({'asin': asin, 'current_price': '1'})
    message = validate_message(message)

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_messages (
            asin TEXT PRIMARY KEY,
            message TEXT NOT NULL,
            updated_at REAL NOT NULL
        )''')
        db.execute(
            '''INSERT INTO review_messages (asin,message,updated_at)
               VALUES (?,?,?)
               ON CONFLICT(asin) DO UPDATE SET
               message=excluded.message,
               updated_at=excluded.updated_at''',
            (asin, message, time.time()),
        )

    return message


def get_message(asin):
    validate({'asin': asin, 'current_price': '1'})

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_messages (
            asin TEXT PRIMARY KEY,
            message TEXT NOT NULL,
            updated_at REAL NOT NULL
        )''')
        row = db.execute(
            'SELECT message FROM review_messages WHERE asin=?',
            (asin,),
        ).fetchone()

    return row[0] if row else None


def save_review_message_id(asin, message_id):
    """Associate a Telegram private-review message with its ASIN."""
    validate({'asin': asin, 'current_price': '1'})

    if type(message_id) is not int or message_id <= 0:
        raise ValueError('INVALID_MESSAGE_ID')

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_message_ids (
            message_id INTEGER PRIMARY KEY,
            asin TEXT NOT NULL,
            created_at REAL NOT NULL
        )''')
        db.execute(
            '''INSERT INTO review_message_ids (message_id, asin, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(message_id) DO UPDATE SET
               asin=excluded.asin,
               created_at=excluded.created_at''',
            (message_id, asin, time.time()),
        )

    return message_id


def resolve_review_asin(message_id):
    """Resolve a known private-review Telegram message to its product."""
    if type(message_id) is not int or message_id <= 0:
        return None

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_message_ids (
            message_id INTEGER PRIMARY KEY,
            asin TEXT NOT NULL,
            created_at REAL NOT NULL
        )''')
        row = db.execute(
            'SELECT asin FROM review_message_ids WHERE message_id=?',
            (message_id,),
        ).fetchone()

    return row[0] if row else None
