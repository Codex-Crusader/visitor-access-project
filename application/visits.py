"""The visits: requests, their gate codes, decisions, and the lists the pages read."""

import json
import random
import secrets
import string
from datetime import datetime, timedelta

from psycopg import errors

import config
import db


def pass_cutoff():
    """A request made before this time can no longer be approved or used."""
    return db.ago(config.PASS_HOURS / 24)


def to_dict(row):
    """A visit as the app uses it. Past PASS_HOURS it reads as expired at once."""
    visit = dict(row)
    visit["guests"] = json.loads(visit["guests"])
    created = str(visit.get("created_at") or "")
    if created:
        expires = datetime.fromisoformat(created) + timedelta(hours=config.PASS_HOURS)
        visit["expires_at"] = expires.isoformat(timespec="seconds")
        if visit.get("status") in db.EXPIRING and created < pass_cutoff():
            visit["status"] = db.EXPIRED
    return visit


CODE_ATTEMPTS = 20
# No I or O, which read as 1 and 0 on a phone screen.
CODE_LETTERS = "".join(c for c in string.ascii_uppercase if c not in "IO")


def new_gate_code():
    """A code like KT-4821, from secrets so it cannot be guessed. Never VR, as in a reference."""
    while True:
        letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(2))
        if letters != "VR":
            return f"{letters}-{secrets.randbelow(10000):04d}"


@db.writes
def create(fields, guests, auto_approve_at=None):
    """Insert a visit and its two codes. Retries when a code is already taken."""
    for _ in range(CODE_ATTEMPTS):
        # Five digits: 90,000 references. Older visits keep their four-digit one.
        reference = f"VR-{random.randint(10000, 99999)}"
        try:
            with db.connect() as conn:
                conn.cursor().executemany(
                    "INSERT INTO gate_codes (code, reference, kind) VALUES (%s, %s, %s)",
                    [(new_gate_code(), reference, db.ENTRY), (new_gate_code(), reference, db.EXIT)],
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
                        db.PENDING,
                        db.now(),
                        auto_approve_at,
                    ),
                ).fetchone()
            return to_dict(row)
        except errors.UniqueViolation:
            continue
    raise RuntimeError("Could not find a free visit code")


@db.read
def get(reference):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM visits WHERE reference = %s", (reference,)
        ).fetchone()
    return to_dict(row) if row is not None else None


@db.cached
@db.read
def _pass_row(token):
    """The visit with this token and its two codes, as stored, or None. One query."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT visits.*, coming.code AS entry_code, going.code AS exit_code"
            " FROM visits"
            " LEFT JOIN gate_codes AS coming"
            "  ON coming.reference = visits.reference AND coming.kind = %s"
            " LEFT JOIN gate_codes AS going"
            "  ON going.reference = visits.reference AND going.kind = %s"
            " WHERE visits.token = %s",
            (db.ENTRY, db.EXIT, token),
        ).fetchone()
    return dict(row) if row else None


def visitor_pass(token):
    """(visit, codes) for the visitor's page, or None. The status is worked out now."""
    row = _pass_row(token)
    if row is None:
        return None
    codes = {db.ENTRY: row.pop("entry_code"), db.EXIT: row.pop("exit_code")}
    return to_dict(row), codes


@db.read
def codes_of(reference) -> dict[str, str]:
    """{"entry": code, "exit": code} for a visit, or {} when it has none."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, code FROM gate_codes WHERE reference = %s", (reference,)
        ).fetchall()
    return {row["kind"]: row["code"] for row in rows}


@db.read
def by_code(code):
    """(visit, kind) for an entry or exit code, or (None, None). One query."""
    with db.connect() as conn:
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


@db.writes
def delete(reference):
    with db.connect() as conn:
        conn.execute("DELETE FROM visits WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM photos WHERE reference = %s", (reference,))
        conn.execute("DELETE FROM gate_codes WHERE reference = %s", (reference,))


@db.read
def all_visits():
    """Every visit, oldest first, with its photo time. For the CSV export."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT visits.*, photos.taken_at AS photo_at FROM visits"
            " LEFT JOIN photos ON photos.reference = visits.reference"
            " ORDER BY visits.created_at"
        ).fetchall()
    return [to_dict(row) for row in rows]


BOARD_FIELDS = "reference, name, visiting, guests, status, created_at, decided_at, entered_at"


@db.cached
@db.read
def _gate_rows():
    """The approved and the inside rows, as stored. Two lookups on the status index."""
    with db.connect() as conn:
        expected = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = %s ORDER BY decided_at DESC",
            (db.APPROVED,),
        ).fetchall()
        inside = conn.execute(
            f"SELECT {BOARD_FIELDS} FROM visits WHERE status = %s ORDER BY entered_at",
            (db.INSIDE,),
        ).fetchall()
    return [dict(row) for row in expected], [dict(row) for row in inside]


def at_gate():
    """(expected, inside) for the gate board. The expiry is worked out now, past any cache."""
    expected, inside = _gate_rows()
    cutoff = pass_cutoff()
    return ([to_dict(row) for row in expected if row["created_at"] >= cutoff],
            [to_dict(row) for row in inside])


# Never SELECT *: the token is the visitor's private link.
ADMIN_FIELDS = (
    "visits.reference, name, phone, address, reason, visiting, guests, status,"
    " created_at, escalated_at, decided_at, decided_by, decided_phone, auto_approve_at,"
    " entered_at, entered_by, exited_at, exited_by"
)


def _like(text):
    """A LIKE pattern that matches text anywhere, with % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@db.read
def admin_page(statuses=None, search="", after=None, limit=50):
    """(visits, cursor) for one admin page, newest first. Keyset paging: page 50 costs as page 1."""
    where, args = [], []
    if statuses:
        where.append(f"status IN ({', '.join(['%s'] * len(statuses))})")
        args += statuses
    if after:
        where.append("(created_at, visits.reference) < (%s, %s)")
        args += after
    if search:
        # A search may read the whole table, one retention period. ILIKE ignores case.
        where.append(
            "(name ILIKE %s ESCAPE '\\' OR phone ILIKE %s ESCAPE '\\'"
            " OR visits.reference ILIKE %s ESCAPE '\\' OR visiting ILIKE %s ESCAPE '\\')"
        )
        args += [_like(search)] * 4
    sql = (
        f"SELECT {ADMIN_FIELDS}, photos.taken_at AS photo_at,"
        " photos.image IS NOT NULL AS photo_stored FROM visits"
        " LEFT JOIN photos ON photos.reference = visits.reference"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY created_at DESC, visits.reference DESC LIMIT %s"
    )
    with db.connect() as conn:
        # One row more than the page tells whether another page exists.
        rows = conn.execute(sql, (*args, limit + 1)).fetchall()
    visits = [to_dict(row) for row in rows[:limit]]
    more = len(rows) > limit
    cursor = (visits[-1]["created_at"], visits[-1]["reference"]) if more else None
    return visits, cursor


@db.read
def status_counts() -> dict[str, int]:
    """How many stored visits have each status. One pass over the status index."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM visits GROUP BY status"
        ).fetchall()
    return {row["status"]: row["count"] for row in rows}


@db.read
def next_due():
    """The earliest time the timer has work, or None. One query on the status indexes."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT (SELECT MIN(created_at) FROM visits WHERE status = %s) AS pending,"
            " (SELECT MIN(auto_approve_at) FROM visits WHERE status IN (%s, %s)) AS auto,"
            " (SELECT MIN(created_at) FROM visits WHERE status IN (%s, %s, %s)) AS expiring",
            (db.PENDING, *db.OPEN_STATUSES, *db.EXPIRING),
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


@db.read
def open_requests():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (%s, %s) ORDER BY created_at",
            db.OPEN_STATUSES,
        ).fetchall()
    return [to_dict(row) for row in rows]


@db.read
def due_for_escalation():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status = %s AND created_at <= %s",
            (db.PENDING, db.ago(config.ESCALATE_MINUTES / 1440)),
        ).fetchall()
    return [to_dict(row) for row in rows]


@db.writes
def mark_escalated(reference):
    with db.connect() as conn:
        conn.execute(
            "UPDATE visits SET status = %s, escalated_at = %s WHERE reference = %s"
            " AND status = %s",
            (db.ESCALATED, db.now(), reference, db.PENDING),
        )


@db.writes
def decide(reference, status, by, phone=None):
    """Record a decision. Returns the visit, or None if it was decided or expired."""
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s, decided_by = %s, decided_phone = %s"
            " WHERE reference = %s AND status IN (%s, %s) AND created_at >= %s RETURNING *",
            (status, db.now(), by, phone, reference, *db.OPEN_STATUSES, pass_cutoff()),
        ).fetchone()
    return to_dict(row) if row is not None else None


@db.read
def due_for_auto_approval():
    """Open requests whose automatic approval time has passed."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM visits WHERE status IN (%s, %s) AND auto_approve_at <= %s",
            (*db.OPEN_STATUSES, db.now()),
        ).fetchall()
    return [to_dict(row) for row in rows]


@db.writes
def expire_old():
    """Save EXPIRED on every pass past PASS_HOURS, so counts and filters match. Returns how many."""
    with db.connect() as conn:
        return conn.execute(
            "UPDATE visits SET status = %s WHERE status IN (%s, %s, %s) AND created_at < %s",
            (db.EXPIRED, *db.EXPIRING, pass_cutoff()),
        ).rowcount


@db.writes
def purge_old():
    """Delete visits after the retention period. Returns how many went."""
    cutoff = db.ago(config.RETAIN_DAYS)
    with db.connect() as conn:
        # Photos and codes go first, with the same cutoff, in the same transaction.
        for table in ("photos", "gate_codes"):
            conn.execute(
                f"DELETE FROM {table} WHERE reference IN"
                " (SELECT reference FROM visits WHERE created_at < %s)",
                (cutoff,),
            )
        removed = conn.execute(
            "DELETE FROM visits WHERE created_at < %s", (cutoff,)
        ).rowcount
        conn.execute("DELETE FROM seen_messages WHERE seen < %s", (db.ago(1),))
        conn.execute("DELETE FROM photo_waits WHERE asked < %s", (db.ago(1),))
    return removed
