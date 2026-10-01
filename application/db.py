"""Postgres storage for visit requests.

The connection string comes from DATABASE_URL. Connections come from a small
pool, because opening a new one to a hosted database takes far longer than
the query itself.
"""

import json
import random
import secrets
import string
import threading
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

# The schema, one step at a time. init() runs every step the database has not
# run yet, in order, and records it in schema_migrations. To change the
# schema, add a new step at the end. Never edit or remove a step that has been
# deployed: databases that already ran it would never run the new text.
#
# While Render deploys a new version, the old version keeps running for a
# moment against the new schema. So a step only adds things: a new table, or
# a new column that is nullable or has a default. To remove a column, stop
# using it in one version, and drop it in a later one.
MIGRATIONS = [
    # 1: the tables as they were when the app moved from SQLite to Postgres.
    """
CREATE TABLE visits (
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

-- WhatsApp message ids already handled, so a retried message runs once.
CREATE TABLE seen_messages (
  id   TEXT PRIMARY KEY,
  seen TEXT NOT NULL
);

-- The guard sent IN <code> and the app is waiting for the visitor's photo.
-- One row per guard number, so a second IN replaces the first.
CREATE TABLE photo_waits (
  guard     TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  asked     TEXT NOT NULL
);

-- The photo the guard took at the gate. The picture itself stays in the gate
-- desk's WhatsApp chat. The app keeps Meta's id for it and the time.
CREATE TABLE photos (
  reference TEXT PRIMARY KEY,
  media_id  TEXT NOT NULL,
  taken_at  TEXT NOT NULL
);

-- The codes on the visitor's pass. Each visit has one entry code and one
-- exit code, and each code does only its own job at the gate. The reference
-- stays with the approvers and opens nothing. The primary key keeps every
-- code unique across both kinds, so no exit code can equal an entry code.
CREATE TABLE gate_codes (
  code      TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  kind      TEXT NOT NULL
);
CREATE INDEX gate_codes_reference ON gate_codes (reference);

-- The escalation sweep, the purge and the open-request list all filter on
-- status and created_at. The admin list pages through visits newest first.
-- reference breaks a tie between two visits made in the same second, so it
-- is in both indexes, and a page starts where the last one ended instead of
-- counting past the rows before it.
CREATE INDEX visits_status_created_ref ON visits (status, created_at, reference);
CREATE INDEX visits_created_ref ON visits (created_at, reference);
-- The gate board's expected list: approved passes by decision time.
CREATE INDEX visits_status_decided ON visits (status, decided_at);
-- The purge deletes old message ids every 30 seconds.
CREATE INDEX seen_messages_seen ON seen_messages (seen);
""",
]

# Any fixed number. Two instances that start at once, as when Render deploys,
# wait for each other here instead of running the same step twice.
MIGRATION_LOCK = 4_022_001

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


_pool = None
_pool_lock = threading.Lock()


def connect() -> AbstractContextManager[Any]:
    """A pooled connection, as a with block that commits at the end.

    An error inside the block rolls everything in it back. The pool opens on
    first use, so importing this module never touches the network.

    prepare_threshold=None turns off prepared statements, which a pooled
    connection string (Neon's -pooler host) cannot keep between transactions.
    The check sends a quick query before handing out a connection, because
    Neon closes idle connections when it scales to zero.

    The connection is typed Any on purpose. The psycopg hints accept only a
    literal string as a query, and the queries here are built from constants
    in this file, never from input. Input always goes in the parameters.
    """
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                config.DATABASE_URL,
                # The four gunicorn threads, plus the background loop.
                min_size=1,
                max_size=5,
                kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 10},
                check=ConnectionPool.check_connection,
                open=True,
            )
    return _pool.connection()


def init():
    """Run every migration this database has not run yet. Returns the version."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        for version, step in enumerate(MIGRATIONS[done:], start=done + 1):
            conn.execute(step)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                (version, now()),
            )
    return len(MIGRATIONS)


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
                conn.cursor().executemany(
                    "INSERT INTO gate_codes (code, reference, kind) VALUES (%s, %s, %s)",
                    [(new_gate_code(), reference, ENTRY), (new_gate_code(), reference, EXIT)],
                )
                conn.execute(
                    "INSERT INTO visits (reference, token, name, phone, address,"
                    " reason, visiting, guests, status, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
        except errors.UniqueViolation:
            continue
    raise RuntimeError("Could not find a free visit code")


def _one(column, value):
    with connect() as conn:
        row = conn.execute(
            f"SELECT * FROM visits WHERE {column} = %s", (value,)
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
            "SELECT kind, code FROM gate_codes WHERE reference = %s", (reference,)
        ).fetchall()
    return {row["kind"]: row["code"] for row in rows}


def by_code(code):
    """(visit, kind) for an entry or exit code, or (None, None)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT reference, kind FROM gate_codes WHERE code = %s", (code,)
        ).fetchone()
    if row is None:
        return None, None
    visit = get(row["reference"])
    return (visit, row["kind"]) if visit is not None else (None, None)


def delete(reference):
    with connect() as conn:
        conn.execute("DELETE FROM visits WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM photos WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM gate_codes WHERE reference = %s", (reference,))


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
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = %s AND decided_at >= %s"
            " ORDER BY decided_at DESC",
            (APPROVED, since),
        ).fetchall()
        inside = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = %s ORDER BY entered_at",
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
        where.append(f"status IN ({', '.join(['%s'] * len(statuses))})")
        args += statuses
    if after:
        where.append("(created_at, visits.reference) < (%s, %s)")
        args += after
    if search:
        # A search reads rows until it fills a page, so a rare word can read
        # the whole table. That is at most one retention period of visits.
        # ILIKE ignores case, as LIKE did on SQLite.
        where.append(
            "(name ILIKE %s ESCAPE '\\' OR phone ILIKE %s ESCAPE '\\'"
            " OR visits.reference ILIKE %s ESCAPE '\\' OR visiting ILIKE %s ESCAPE '\\')"
        )
        args += [_like(search)] * 4
    sql = (
        f"SELECT {ADMIN_FIELDS}, photos.taken_at AS photo_at FROM visits"
        " LEFT JOIN photos ON photos.reference = visits.reference"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY created_at DESC, visits.reference DESC LIMIT %s"
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
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM visits GROUP BY status"
        ).fetchall()
    return {row["status"]: row["count"] for row in rows}


def open_requests():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (%s, %s) ORDER BY created_at",
            OPEN_STATUSES,
        ).fetchall()
    return [to_dict(row) for row in rows]


def due_for_escalation():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status = %s AND created_at <= %s",
            (PENDING, ago(config.ESCALATE_MINUTES / 1440)),
        ).fetchall()
    return [to_dict(row) for row in rows]


def mark_escalated(reference):
    with connect() as conn:
        conn.execute(
            "UPDATE visits SET status = %s, escalated_at = %s WHERE reference = %s"
            " AND status = %s",
            (ESCALATED, now(), reference, PENDING),
        )


def decide(reference, status):
    """Record a decision. Returns False if the request was already decided."""
    with connect() as conn:
        changed = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s WHERE reference = %s"
            " AND status IN (%s, %s)",
            (status, now(), reference, *OPEN_STATUSES),
        ).rowcount
    return changed == 1


def _stamp(reference, status, column, required):
    with connect() as conn:
        changed = conn.execute(
            f"UPDATE visits SET status = %s, {column} = %s WHERE reference = %s"
            " AND status = %s",
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
            "INSERT INTO photo_waits (guard, reference, asked) VALUES (%s, %s, %s)"
            " ON CONFLICT (guard) DO UPDATE"
            " SET reference = EXCLUDED.reference, asked = EXCLUDED.asked",
            (guard, reference, now()),
        )


def enter_with_photo(guard, minutes, media_id):
    """Let in the visitor this guard's photo is for. Returns (reference, entered).

    reference is None when no IN from this guard is waiting, or when the IN is
    older than `minutes`. entered is False unless the pass was approved.

    Every photo ends the wait, so a second photo can never let a second person
    in on the same IN. Everything happens in one transaction: if any step
    fails, the wait is still there and the guard can send the photo again.
    The wait is read and deleted in one statement, so of two photos sent at
    the same moment, only one gets it.
    """
    with connect() as conn:
        wait = conn.execute(
            "DELETE FROM photo_waits WHERE guard = %s RETURNING reference, asked", (guard,)
        ).fetchone()
        if wait is None or wait["asked"] < ago(minutes / 1440):
            return None, False

        reference, stamp = wait["reference"], now()
        changed = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s WHERE reference = %s AND status = %s",
            (INSIDE, stamp, reference, APPROVED),
        ).rowcount
        if changed == 1:
            conn.execute(
                "INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (reference) DO UPDATE"
                " SET media_id = EXCLUDED.media_id, taken_at = EXCLUDED.taken_at",
                (reference, media_id, stamp),
            )
    return reference, changed == 1


def photo_of(reference):
    """The stored photo record for a pass, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT media_id, taken_at FROM photos WHERE reference = %s", (reference,)
        ).fetchone()
    return dict(row) if row else None


def is_new_message(message_id):
    """False when this WhatsApp message was already handled."""
    if not message_id:
        return True
    with connect() as conn:
        added = conn.execute(
            "INSERT INTO seen_messages (id, seen) VALUES (%s, %s) ON CONFLICT DO NOTHING",
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
                " (SELECT reference FROM visits WHERE created_at < %s)",
                (cutoff,),
            )
        removed = conn.execute(
            "DELETE FROM visits WHERE created_at < %s", (cutoff,)
        ).rowcount
        conn.execute("DELETE FROM seen_messages WHERE seen < %s", (ago(1),))
        conn.execute("DELETE FROM photo_waits WHERE asked < %s", (ago(1),))
    return removed
