"""Persistent Telegram polling offset for V16."""
from review_store import connect


def get_offset():
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_polling (
            name TEXT PRIMARY KEY,
            next_offset INTEGER NOT NULL
        )''')
        row = db.execute(
            "SELECT next_offset FROM review_polling WHERE name='telegram'"
        ).fetchone()
    return row[0] if row else None


def save_offset(next_offset):
    if type(next_offset) is not int or next_offset < 0:
        raise ValueError('INVALID_OFFSET')

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_polling (
            name TEXT PRIMARY KEY,
            next_offset INTEGER NOT NULL
        )''')
        db.execute(
            '''INSERT INTO review_polling(name,next_offset)
               VALUES ('telegram',?)
               ON CONFLICT(name) DO UPDATE SET
               next_offset=MAX(next_offset,excluded.next_offset)''',
            (next_offset,),
        )

    return get_offset()
