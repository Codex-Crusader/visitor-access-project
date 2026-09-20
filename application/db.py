"""SQLite storage for visit requests. Each call opens its own connection."""

import json
import random
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
  reference    TEXT PRIMARY KEY,
  token        TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  phone        TEXT NOT NULL,
  address      TEXT NOT NULL,
  reason       TEXT NOT NULL,
  visiting     TEXT NOT NULL,
  guests       TEXT NOT NULL,
  status       TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  escalated_at TEXT,
  decided_at   TEXT,
  entered_at   TEXT,
  exited_at    TEXT
);

CREATE TABLE IF NOT EXISTS seen_messages (
  id   TEXT PRIMARY KEY,
  seen TEXT NOT NULL
);
"""

PENDING = "pending"
ESCALATED = "escalated"
APPROVED = "approved"
DECLINED = "declined"
INSIDE = "inside"
CLOSED = "closed"
OPEN_STATUSES = (PENDING, ESCALATED)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def to_dict(row):
    if row is None:
        return None
    visit = dict(row)
    visit["guests"] = json.loads(visit["guests"])
    return visit


CODE_ATTEMPTS = 20


def create(fields, guests):
    """Insert a visit. Retries when two requests pick the same code at once."""
    for _ in range(CODE_ATTEMPTS):
        reference = f"VR-{random.randint(1000, 9999)}"
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO visits (reference, token, name, phone, address,"
                    " reason, visiting, guests, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        reference,
                        secrets.token_urlsafe(16),
                        fields["name"],
                        fields["phone"],
                        fields["address"],
                        fields["reason"],
                        fields["visiting"],
                        json.dumps(guests),
                        PENDING,
                        now(),
                    ),
                )
            return get(reference)
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("Could not find a free visit code")


def _one(column, value):
    with connect() as conn:
        row = conn.execute(
            f"SELECT * FROM visits WHERE {column} = ?", (value,)
        ).fetchone()
    return to_dict(row)


def get(reference):
    return _one("reference", reference)


def get_by_token(token):
    return _one("token", token)


def delete(reference):
    with connect() as conn:
        conn.execute("DELETE FROM visits WHERE reference = ?", (reference,))


def all_visits():
    """Every stored visit, oldest first. Used by the export."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM visits ORDER BY created_at").fetchall()
    return [to_dict(row) for row in rows]


def open_requests():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (?, ?) ORDER BY created_at",
            OPEN_STATUSES,
        ).fetchall()
    return [to_dict(row) for row in rows]


def due_for_escalation():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status = ? AND created_at <= ?",
            (PENDING, _ago(config.ESCALATE_MINUTES / 1440)),
        ).fetchall()
    return [to_dict(row) for row in rows]


def mark_escalated(reference):
    with connect() as conn:
        conn.execute(
            "UPDATE visits SET status = ?, escalated_at = ? WHERE reference = ?"
            " AND status = ?",
            (ESCALATED, now(), reference, PENDING),
        )


def decide(reference, status):
    """Record a decision. Returns False if the request was already decided."""
    with connect() as conn:
        changed = conn.execute(
            "UPDATE visits SET status = ?, decided_at = ? WHERE reference = ?"
            " AND status IN (?, ?)",
            (status, now(), reference, *OPEN_STATUSES),
        ).rowcount
    return changed == 1


def _stamp(reference, status, column, required):
    with connect() as conn:
        changed = conn.execute(
            f"UPDATE visits SET status = ?, {column} = ? WHERE reference = ?"
            " AND status = ?",
            (status, now(), reference, required),
        ).rowcount
    return changed == 1


def check_in(reference):
    """Let an approved visitor in. Returns False unless the pass is approved."""
    return _stamp(reference, INSIDE, "entered_at", APPROVED)


def check_out(reference):
    """Close the pass on the way out. Returns False unless the visitor is inside."""
    return _stamp(reference, CLOSED, "exited_at", INSIDE)


def is_new_message(message_id):
    """False when this WhatsApp message was already handled."""
    if not message_id:
        return True
    with connect() as conn:
        added = conn.execute(
            "INSERT OR IGNORE INTO seen_messages (id, seen) VALUES (?, ?)",
            (message_id, now()),
        ).rowcount
    return added == 1


def purge_old():
    """Delete visits after the retention period. Returns how many went."""
    with connect() as conn:
        removed = conn.execute(
            "DELETE FROM visits WHERE created_at < ?", (_ago(config.RETAIN_DAYS),)
        ).rowcount
        conn.execute("DELETE FROM seen_messages WHERE seen < ?", (_ago(1),))
    return removed
