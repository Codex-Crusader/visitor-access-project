"""SQLite storage for visit requests. Each call opens its own connection."""

import json
import random
import secrets
import sqlite3
import string
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

-- The guard sent IN <code> and the app is waiting for the visitor's photo.
-- One row per guard number, so a second IN replaces the first. These are
-- tables of their own rather than new columns on visits, because CREATE TABLE
-- IF NOT EXISTS never adds a column to a database that already exists.
CREATE TABLE IF NOT EXISTS photo_waits (
  guard     TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  asked     TEXT NOT NULL
);

-- The photo the guard took at the gate. The picture itself stays in the gate
-- desk's WhatsApp chat. The app keeps Meta's id for it and the time.
CREATE TABLE IF NOT EXISTS photos (
  reference TEXT PRIMARY KEY,
  media_id  TEXT NOT NULL,
  taken_at  TEXT NOT NULL
);

-- The codes on the visitor's pass. Each visit has one entry code and one
-- exit code, and each code does only its own job at the gate. The reference
-- stays with the approvers and opens nothing. The primary key keeps every
-- code unique across both kinds, so no exit code can equal an entry code.
CREATE TABLE IF NOT EXISTS gate_codes (
  code      TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  kind      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gate_codes_reference ON gate_codes (reference);

-- The escalation sweep, the purge and the open-request list all filter on
-- status and created_at. Without this they scan every row every 30 seconds.
-- The admin list pages through visits newest first. reference breaks a tie
-- between two visits made in the same second, so it is in both indexes, and
-- a page starts where the last one ended instead of counting past the rows
-- before it. The old two-column indexes are dropped: a prefix of the new
-- ones serves every query they served.
DROP INDEX IF EXISTS visits_status_created;
DROP INDEX IF EXISTS visits_created;
CREATE INDEX IF NOT EXISTS visits_status_created_ref ON visits (status, created_at, reference);
CREATE INDEX IF NOT EXISTS visits_created_ref ON visits (created_at, reference);
-- The gate board's expected list: approved passes by decision time. Passes
-- that nobody used pile up over the retention period, so without this the
-- board reads all of them every 30 seconds.
CREATE INDEX IF NOT EXISTS visits_status_decided ON visits (status, decided_at);
-- The purge also deletes old message ids every 30 seconds. Without this it
-- reads the whole table each time to find the few that are old.
CREATE INDEX IF NOT EXISTS seen_messages_seen ON seen_messages (seen);
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


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def to_dict(row):
    visit = dict(row)
    visit["guests"] = json.loads(visit["guests"])
    return visit


CODE_ATTEMPTS = 20
ENTRY = "entry"
EXIT = "exit"
# No I or O, which read as 1 and 0 on a phone screen.
CODE_LETTERS = "".join(c for c in string.ascii_uppercase if c not in "IO")


def new_gate_code():
    """A random code such as KT-4821. VR is left out, because VR-4821 is a reference.

    The codes come from secrets, not random: a code that lets a person onto
    the campus must not be predictable from the ones before it.
    """
    while True:
        letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(2))
        if letters != "VR":
            return f"{letters}-{secrets.randbelow(10000):04d}"


def create(fields, guests):
    """Insert a visit and its two codes. Retries when a code is already taken."""
    for _ in range(CODE_ATTEMPTS):
        reference = f"VR-{random.randint(1000, 9999)}"
        try:
            with connect() as conn:
                conn.executemany(
                    "INSERT INTO gate_codes (code, reference, kind) VALUES (?, ?, ?)",
                    [(new_gate_code(), reference, ENTRY), (new_gate_code(), reference, EXIT)],
                )
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
    return to_dict(row) if row is not None else None


def get(reference):
    return _one("reference", reference)


def get_by_token(token):
    return _one("token", token)


def codes_of(reference) -> dict[str, str]:
    """{"entry": code, "exit": code} for a visit, or {} when it has none."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT kind, code FROM gate_codes WHERE reference = ?", (reference,)
        ).fetchall()
    return dict(rows)


def by_code(code):
    """(visit, kind) for an entry or exit code, or (None, None)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT reference, kind FROM gate_codes WHERE code = ?", (code,)
        ).fetchone()
    if row is None:
        return None, None
    visit = get(row["reference"])
    return (visit, row["kind"]) if visit is not None else (None, None)


def delete(reference):
    with connect() as conn:
        conn.execute("DELETE FROM visits WHERE reference = ?", (reference,))
        conn.execute("DELETE FROM photos WHERE reference = ?", (reference,))
        conn.execute("DELETE FROM gate_codes WHERE reference = ?", (reference,))


def all_visits():
    """Every stored visit, oldest first, with the time of its gate photo.

    Used by the export. The photo time comes from one join rather than one
    lookup per visit.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT visits.*, photos.taken_at AS photo_at FROM visits"
            " LEFT JOIN photos ON photos.reference = visits.reference"
            " ORDER BY visits.created_at"
        ).fetchall()
    return [to_dict(row) for row in rows]


BOARD_FIELDS = "reference, name, visiting, guests, status, decided_at, entered_at"


def at_gate(expected_hours):
    """What the gate desk board shows: (expected, inside).

    expected is every pass approved in the last `expected_hours` and not used
    yet, newest first. inside is everyone inside now, longest inside first, so
    a visitor who never left is at the top. Two queries, each one a lookup on
    the status index, rather than one OR that reads the whole table.
    """
    since = ago(expected_hours / 24)
    with connect() as conn:
        expected = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = ? AND decided_at >= ?"
            " ORDER BY decided_at DESC",
            (APPROVED, since),
        ).fetchall()
        inside = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = ? ORDER BY entered_at",
            (INSIDE,),
        ).fetchall()
    return [to_dict(row) for row in expected], [to_dict(row) for row in inside]


# Everything the admin page shows. Never SELECT * here: the token is the
# visitor's private status link and must not leave the server.
ADMIN_FIELDS = (
    "visits.reference, name, phone, address, reason, visiting, guests, status,"
    " created_at, escalated_at, decided_at, entered_at, exited_at"
)


def _like(text):
    """A LIKE pattern that matches text anywhere, with % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def admin_page(statuses=None, search="", after=None, limit=50):
    """One page of visits for the admin list, newest first.

    Returns (visits, cursor). Pass cursor back as `after` for the next page.
    It is None on the last page. A page is a range read on an index that
    starts right after the previous page's last row, so page 50 costs the same
    as page 1. OFFSET would read and throw away every row before the page.
    """
    where, args = [], []
    if statuses:
        where.append(f"status IN ({', '.join('?' * len(statuses))})")
        args += statuses
    if after:
        where.append("(created_at, visits.reference) < (?, ?)")
        args += after
    if search:
        # A search reads rows until it fills a page, so a rare word can read
        # the whole table. That is at most one retention period of visits.
        where.append(
            "(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\'"
            " OR visits.reference LIKE ? ESCAPE '\\' OR visiting LIKE ? ESCAPE '\\')"
        )
        args += [_like(search)] * 4
    sql = (
        f"SELECT {ADMIN_FIELDS}, photos.taken_at AS photo_at FROM visits"
        " LEFT JOIN photos ON photos.reference = visits.reference"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY created_at DESC, visits.reference DESC LIMIT ?"
    )
    with connect() as conn:
        # One row more than the page tells whether another page exists.
        rows = conn.execute(sql, (*args, limit + 1)).fetchall()
    visits = [to_dict(row) for row in rows[:limit]]
    more = len(rows) > limit
    cursor = (visits[-1]["created_at"], visits[-1]["reference"]) if more else None
    return visits, cursor


def status_counts() -> dict[str, int]:
    """How many stored visits have each status. One pass over the status index."""
    with connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) FROM visits GROUP BY status").fetchall()
    return dict(rows)


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
            (PENDING, ago(config.ESCALATE_MINUTES / 1440)),
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


def wait_for_photo(guard, reference):
    """Remember that this guard owes a photo for this pass. Replaces any earlier one."""
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO photo_waits (guard, reference, asked) VALUES (?, ?, ?)",
            (guard, reference, now()),
        )


def enter_with_photo(guard, minutes, media_id):
    """Let in the visitor this guard's photo is for. Returns (reference, entered).

    reference is None when no IN from this guard is waiting, or when the IN is
    older than `minutes`. entered is False unless the pass was approved.

    Every photo ends the wait, so a second photo can never let a second person
    in on the same IN. Everything happens in one transaction: if any step
    fails, the wait is still there and the guard can send the photo again.
    """
    with connect() as conn:
        wait = conn.execute(
            "SELECT reference, asked FROM photo_waits WHERE guard = ?", (guard,)
        ).fetchone()
        conn.execute("DELETE FROM photo_waits WHERE guard = ?", (guard,))
        if wait is None or wait["asked"] < ago(minutes / 1440):
            return None, False

        reference, stamp = wait["reference"], now()
        changed = conn.execute(
            "UPDATE visits SET status = ?, entered_at = ? WHERE reference = ? AND status = ?",
            (INSIDE, stamp, reference, APPROVED),
        ).rowcount
        if changed == 1:
            conn.execute(
                "INSERT OR REPLACE INTO photos (reference, media_id, taken_at)"
                " VALUES (?, ?, ?)",
                (reference, media_id, stamp),
            )
    return reference, changed == 1


def photo_of(reference):
    """The stored photo record for a pass, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT media_id, taken_at FROM photos WHERE reference = ?", (reference,)
        ).fetchone()
    return dict(row) if row else None


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
    cutoff = ago(config.RETAIN_DAYS)
    with connect() as conn:
        # A photo and the two codes go with their visit, so they are deleted
        # first, in the same transaction and with the same cutoff. This reads
        # only the expired visits. The old way asked every photo whether its
        # visit still existed, every 30 seconds.
        for table in ("photos", "gate_codes"):
            conn.execute(
                f"DELETE FROM {table} WHERE reference IN"
                " (SELECT reference FROM visits WHERE created_at < ?)",
                (cutoff,),
            )
        removed = conn.execute(
            "DELETE FROM visits WHERE created_at < ?", (cutoff,)
        ).rowcount
        conn.execute("DELETE FROM seen_messages WHERE seen < ?", (ago(1),))
        conn.execute("DELETE FROM photo_waits WHERE asked < ?", (ago(1),))
    return removed
