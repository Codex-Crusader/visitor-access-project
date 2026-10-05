"""Postgres storage for visit requests.

The connection string comes from DATABASE_URL. Connections come from a small
pool, because opening a new one to a hosted database takes far longer than
the query itself.
"""

import atexit
import functools
import json
import logging
import random
import secrets
import string
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import OperationalError, errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

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
    # 2: approvers set on the admin page, and auto-approval.
    """
-- Set on the admin page. A reason with no row uses the settings.
CREATE TABLE approvers (
  reason     TEXT PRIMARY KEY,
  main       TEXT NOT NULL,
  backup     TEXT NOT NULL,
  changed_at TEXT NOT NULL
);

-- Empty for a request made outside working hours.
ALTER TABLE visits ADD COLUMN auto_approve_at TEXT;
-- main, backup or auto. Never a phone: the visitor's page shows this row.
ALTER TABLE visits ADD COLUMN decided_by TEXT;
CREATE INDEX visits_status_auto ON visits (status, auto_approve_at);
""",
    # 3: the number that decided, for the admin page only.
    """
-- The approver's number as set when they decided. Empty for an automatic
-- approval and for decisions made before this step.
ALTER TABLE visits ADD COLUMN decided_phone TEXT;
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
# Not approved and not used within PASS_HOURS of the request.
EXPIRED = "expired"
OPEN_STATUSES = (PENDING, ESCALATED)
# The statuses that turn to EXPIRED once PASS_HOURS have passed.
EXPIRING = (PENDING, ESCALATED, APPROVED)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# The open pool, or none yet. A list, so its type is never None.
_pools: list[ConnectionPool] = []
_pool_lock = threading.Lock()
_closed = False


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
    with _pool_lock:
        if _closed:
            raise RuntimeError("The database is closed: the app is shutting down")
        if not _pools:
            _pools.append(ConnectionPool(
                config.DATABASE_URL,
                # The four gunicorn threads, plus the background loop. Two stay
                # open, so the timer and a request never wait for a new one.
                min_size=2,
                max_size=5,
                # A request waits at most 5 seconds for a connection. The same
                # four threads serve the pages, so a slow database must not
                # hold them long. The visitor page gives up at 10 seconds.
                timeout=5,
                # A connection attempt that hangs fails after 10 seconds and
                # is tried again, instead of holding a waiting request forever.
                # Keepalives notice a connection that died without a word in
                # about a minute, not the two hours the system waits by default.
                kwargs={
                    "row_factory": dict_row,
                    "prepare_threshold": None,
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 3,
                },
                check=ConnectionPool.check_connection,
                open=True,
            ))
    return _pools[0].connection()


def close():
    """Close the pool and its helper threads. Safe to call more than once.

    Call it before the process exits. A pool left open is closed by Python's
    own cleanup during interpreter shutdown, when Python 3.14 can no longer
    join its threads: the connections are dropped instead of closed, and the
    log shows PythonFinalizationError. After close(), connect() refuses, so
    nothing opens a new pool on the way out.
    """
    global _closed
    with _pool_lock:
        _closed = True
        closing = _pools[:]
        _pools.clear()
    for pool in closing:
        pool.close(timeout=5)


# Scripts and tests that open the database close it on exit too. The app
# itself stops its timer first, see app.stop_background().
atexit.register(close)

log = logging.getLogger(__name__)

# Seconds to wait before each new try when the database cannot be reached at
# start. Neon takes a moment to wake, and gunicorn stops the whole server when
# its worker fails to start, so the start waits about 15 seconds before it
# gives up.
START_WAITS = (1, 2, 4, 8)


def init():
    """Run every migration this database has not run yet. Returns the version.

    A connection that fails is tried again after each of START_WAITS.
    """
    for wait in START_WAITS:
        try:
            return migrate()
        except OperationalError as failure:
            log.warning("Database not reachable at start, again in %ss: %s", wait, failure)
            time.sleep(wait)
    return migrate()


def migrate():
    """One attempt at init(): run the migrations that are new to this database."""
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


def read(query):
    """Run a read a second time when its connection breaks under it.

    Neon can close a connection at any moment, for example when it scales to
    zero. A read changes nothing, so a second run is safe. Writes are never
    run twice, because a COMMIT can land even when its reply is lost. A full
    pool is not tried again either: that would only double the wait.
    """
    @functools.wraps(query)
    def read_again(*args, **kwargs):
        try:
            return query(*args, **kwargs)
        except PoolTimeout:
            raise
        except OperationalError:
            return query(*args, **kwargs)
    return read_again


def pass_cutoff():
    """A request made before this time can no longer be approved or used."""
    return ago(config.PASS_HOURS / 24)


def to_dict(row):
    """A visit as the app uses it. A pass past PASS_HOURS reads as expired at once,
    before the background round saves that status."""
    visit = dict(row)
    visit["guests"] = json.loads(visit["guests"])
    created = visit.get("created_at")
    if created:
        expires = datetime.fromisoformat(created) + timedelta(hours=config.PASS_HOURS)
        visit["expires_at"] = expires.isoformat(timespec="seconds")
        if visit.get("status") in EXPIRING and created < pass_cutoff():
            visit["status"] = EXPIRED
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


def create(fields, guests, auto_approve_at=None):
    """Insert a visit and its two codes. Retries when a code is already taken."""
    for _ in range(CODE_ATTEMPTS):
        reference = f"VR-{random.randint(1000, 9999)}"
        try:
            with connect() as conn:
                conn.cursor().executemany(
                    "INSERT INTO gate_codes (code, reference, kind) VALUES (%s, %s, %s)",
                    [(new_gate_code(), reference, ENTRY), (new_gate_code(), reference, EXIT)],
                )
                row = conn.execute(
                    "INSERT INTO visits (reference, token, name, phone, address,"
                    " reason, visiting, guests, status, created_at, auto_approve_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
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
                        auto_approve_at,
                    ),
                ).fetchone()
            return to_dict(row)
        except errors.UniqueViolation:
            continue
    raise RuntimeError("Could not find a free visit code")


@read
def get(reference):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM visits WHERE reference = %s", (reference,)
        ).fetchone()
    return to_dict(row) if row is not None else None


@read
def visitor_pass(token):
    """(visit, {"entry": code, "exit": code}) for the visitor's page, or (None, {}).

    One query: the page asks every three seconds, often on a weak signal.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT visits.*, coming.code AS entry_code, going.code AS exit_code"
            " FROM visits"
            " LEFT JOIN gate_codes AS coming"
            "  ON coming.reference = visits.reference AND coming.kind = %s"
            " LEFT JOIN gate_codes AS going"
            "  ON going.reference = visits.reference AND going.kind = %s"
            " WHERE visits.token = %s",
            (ENTRY, EXIT, token),
        ).fetchone()
    if row is None:
        return None, {}
    codes = {ENTRY: row.pop("entry_code"), EXIT: row.pop("exit_code")}
    return to_dict(row), codes


@read
def codes_of(reference) -> dict[str, str]:
    """{"entry": code, "exit": code} for a visit, or {} when it has none."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT kind, code FROM gate_codes WHERE reference = %s", (reference,)
        ).fetchall()
    return {row["kind"]: row["code"] for row in rows}


@read
def by_code(code):
    """(visit, kind) for an entry or exit code, or (None, None). One query."""
    with connect() as conn:
        row = conn.execute(
            "SELECT visits.*, gate_codes.kind AS code_kind FROM gate_codes"
            " JOIN visits ON visits.reference = gate_codes.reference"
            " WHERE gate_codes.code = %s",
            (code,),
        ).fetchone()
    if row is None:
        return None, None
    kind = row.pop("code_kind")
    return to_dict(row), kind


def delete(reference):
    with connect() as conn:
        conn.execute("DELETE FROM visits WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM photos WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM gate_codes WHERE reference = %s", (reference,))


@read
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


BOARD_FIELDS = "reference, name, visiting, guests, status, created_at, decided_at, entered_at"


@read
def at_gate():
    """What the gate desk board shows: (expected, inside).

    expected is every approved pass that has not expired or been used, newest
    decision first. inside is everyone inside now, longest inside first, so a
    visitor who never left is at the top. Two queries, each one a lookup on
    the status index, rather than one OR that reads the whole table.
    """
    with connect() as conn:
        expected = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = %s AND created_at >= %s"
            " ORDER BY decided_at DESC",
            (APPROVED, pass_cutoff()),
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
    " created_at, escalated_at, decided_at, decided_by, decided_phone, auto_approve_at,"
    " entered_at, exited_at"
)


def _like(text):
    """A LIKE pattern that matches text anywhere, with % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@read
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
        # ILIKE ignores case, so a search in small letters finds a name in capitals.
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


@read
def status_counts() -> dict[str, int]:
    """How many stored visits have each status. One pass over the status index."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM visits GROUP BY status"
        ).fetchall()
    return {row["status"]: row["count"] for row in rows}


def ping():
    """True when the database answers. For the health check."""
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # any failure means the check failed
        return False


@read
def next_due():
    """The earliest time the background round has work, or None when nothing waits.

    Work is an escalation, an automatic approval, or a pass that expires. One
    query, three lookups on the status indexes.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT (SELECT MIN(created_at) FROM visits WHERE status = %s) AS pending,"
            " (SELECT MIN(auto_approve_at) FROM visits WHERE status IN (%s, %s)) AS auto,"
            " (SELECT MIN(created_at) FROM visits WHERE status IN (%s, %s, %s)) AS expiring",
            (PENDING, *OPEN_STATUSES, *EXPIRING),
        ).fetchone()
    times = []
    if row["pending"]:
        times.append(datetime.fromisoformat(row["pending"])
                     + timedelta(minutes=config.ESCALATE_MINUTES))
    if row["auto"]:
        times.append(datetime.fromisoformat(row["auto"]))
    if row["expiring"]:
        times.append(datetime.fromisoformat(row["expiring"]) + timedelta(hours=config.PASS_HOURS))
    return min(times) if times else None


@read
def open_requests():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (%s, %s) ORDER BY created_at",
            OPEN_STATUSES,
        ).fetchall()
    return [to_dict(row) for row in rows]


@read
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


# Values of decided_by.
BY_MAIN = "main"
BY_BACKUP = "backup"
BY_AUTO = "auto"


def decide(reference, status, by, phone=None):
    """Record a decision. Returns the visit, or None if it was decided or expired."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s, decided_by = %s, decided_phone = %s"
            " WHERE reference = %s AND status IN (%s, %s) AND created_at >= %s RETURNING *",
            (status, now(), by, phone, reference, *OPEN_STATUSES, pass_cutoff()),
        ).fetchone()
    return to_dict(row) if row is not None else None


@read
def due_for_auto_approval():
    """Open requests whose automatic approval time has passed."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (%s, %s) AND auto_approve_at <= %s",
            (*OPEN_STATUSES, now()),
        ).fetchall()
    return [to_dict(row) for row in rows]


@read
def approver_table():
    """Each reason's (main, backup): the admin page's choice, else the settings."""
    with connect() as conn:
        rows = conn.execute("SELECT reason, main, backup FROM approvers").fetchall()
    table = dict(config.APPROVERS)
    table.update({row["reason"]: (row["main"], row["backup"])
                  for row in rows if row["reason"] in table})
    return table


def approvers_for(table, reason):
    """(main, backup) for a visit's reason. A typed-in reason counts as the reason Other."""
    return table.get(reason, table["Other"])


def save_approvers(reason, main, backup):
    """Set a reason's two approvers, in place of the settings."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO approvers (reason, main, backup, changed_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (reason) DO UPDATE SET main = EXCLUDED.main,"
            " backup = EXCLUDED.backup, changed_at = EXCLUDED.changed_at",
            (reason, main, backup, now()),
        )


def _stamp(reference, status, column, required):
    """Move a visit on, if it is in the required status. Returns it as it is now, or None.

    The condition sits in the UPDATE itself, so of two guards at the same
    moment exactly one gets the visit back.
    """
    with connect() as conn:
        row = conn.execute(
            f"UPDATE visits SET status = %s, {column} = %s WHERE reference = %s"
            " AND status = %s RETURNING *",
            (status, now(), reference, required),
        ).fetchone()
    return to_dict(row) if row is not None else None


def check_in(reference):
    """Let an approved visitor in. Returns the visit, or None unless the pass is approved
    and not expired. The time check is in the UPDATE, so a pass cannot expire halfway."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s RETURNING *",
            (INSIDE, now(), reference, APPROVED, pass_cutoff()),
        ).fetchone()
    return to_dict(row) if row is not None else None


def check_out(reference):
    """Close the pass on the way out. Returns the visit, or None unless the visitor is inside."""
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
            "UPDATE visits SET status = %s, entered_at = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s",
            (INSIDE, stamp, reference, APPROVED, pass_cutoff()),
        ).rowcount
        if changed == 1:
            conn.execute(
                "INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (reference) DO UPDATE"
                " SET media_id = EXCLUDED.media_id, taken_at = EXCLUDED.taken_at",
                (reference, media_id, stamp),
            )
    return reference, changed == 1


@read
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


def expire_old():
    """Save EXPIRED on every pass past PASS_HOURS, so counts and filters match. Returns how many."""
    with connect() as conn:
        return conn.execute(
            "UPDATE visits SET status = %s WHERE status IN (%s, %s, %s) AND created_at < %s",
            (EXPIRED, *EXPIRING, pass_cutoff()),
        ).rowcount


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
