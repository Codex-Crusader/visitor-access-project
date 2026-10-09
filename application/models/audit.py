"""The admin change log: who changed a list, a number or a key, and when. Never a key itself."""

import logging

from core import db

log = logging.getLogger("app")
FIELDS = "at, by_whom, action, detail"


@db.writes
def record(by, action, detail=""):
    """Keep one change. A failure here is logged and never undoes the change."""
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO admin_changes (at, by_whom, action, detail) VALUES (%s, %s, %s, %s)",
                (db.now(), by or "Unknown", action, detail),
            )
    except Exception as failure:  # the change itself is already saved
        log.error("Could not record an admin change: %s", failure)


@db.cached
@db.read
def recent(limit=100):
    """The newest changes, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {FIELDS} FROM admin_changes ORDER BY at DESC, id DESC LIMIT %s", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


@db.read
def everything():
    """Every change still kept, oldest first. For the log download."""
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {FIELDS} FROM admin_changes ORDER BY at, id").fetchall()
    return [dict(row) for row in rows]
