"""The visits: requests, their gate codes, decisions, and the lists the pages read."""

import json
import random
import secrets
import string
from datetime import datetime, timedelta

from psycopg import errors

from core import config, db
from models import blacklist


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


class SameRequest(Exception):
    """The browser sent this filled-in form before. visit is the request it made then."""

    def __init__(self, visit):
        super().__init__(visit["reference"])
        self.visit = visit


@db.read
def by_request_key(key):
    """The visit made with this browser key, or None."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM visits WHERE request_key = %s", (key,)).fetchone()
    return to_dict(row) if row is not None else None


@db.writes
def create(fields, guests, auto_approve_at=None, office=None, request_key=None):
    """Insert a visit and its two codes. Retries when a code is already taken.

    Raises SameRequest when request_key made a visit before, also from a request sent at the
    same time."""
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
                    " reason, visiting, guests, status, created_at, auto_approve_at, office,"
                    " request_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " RETURNING *",
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
                        office,
                        request_key,
                    ),
                ).fetchone()
            return to_dict(row)
        except errors.UniqueViolation as clash:
            if clash.diag.constraint_name == "visits_request_key":
                earlier = by_request_key(request_key)
                # Gone already: the first request failed to send and was deleted. This one goes on.
                if earlier is not None:
                    raise SameRequest(earlier) from None
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
            "SELECT visits.*, photos.taken_at AS photo_at,"
            " photos.image IS NOT NULL AS photo_stored FROM visits"
            " LEFT JOIN photos ON photos.reference = visits.reference"
            " ORDER BY visits.created_at"
        ).fetchall()
    return [to_dict(row) for row in rows]


# The phone is read only to check the blacklist. The gate route drops it.
BOARD_FIELDS = ("reference, name, phone, visiting, guests, status, created_at, decided_at,"
                " entered_at")


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
    "visits.reference, name, phone, address, reason, office, visiting, guests, status,"
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
    """The earliest time the timer has work, or None. One query on the status indexes.

    Each MIN takes one status, so it reads the first row of that status on the (status,
    created_at) index: O(log n). One MIN over three statuses walked the created_at index from
    the oldest visit instead, O(n): 200,000 rows read for one."""
    oldest = " (SELECT MIN(created_at) FROM visits WHERE status = %s)"
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT{oldest} AS pending,"
            " (SELECT MIN(auto_approve_at) FROM visits WHERE status IN (%s, %s)) AS auto,"
            f" LEAST({','.join([oldest] * len(db.EXPIRING))}) AS expiring",
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
def stop_auto_approval(reference):
    """A request no approver may have seen is never approved by itself."""
    with db.connect() as conn:
        conn.execute("UPDATE visits SET auto_approve_at = NULL WHERE reference = %s",
                     (reference,))


@db.writes
def move_auto_approval(reference, at):
    """Give an open request that approves by itself a new time. None: it waits for a person."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE visits SET auto_approve_at = %s WHERE reference = %s"
            " AND status IN (%s, %s) AND auto_approve_at IS NOT NULL",
            (at, reference, *db.OPEN_STATUSES),
        )


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
    """Record a decision. Returns the visit, or None if it was decided, expired, or is an
    approval for a number on the blacklist."""
    # In the UPDATE, so a YES or an automatic approval that races the ban loses.
    listed = blacklist.not_listed("visits.phone") if status == db.APPROVED else ""
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s, decided_by = %s, decided_phone = %s"
            " WHERE reference = %s AND status IN (%s, %s) AND created_at >= %s" + listed
            + " RETURNING *",
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
    """Delete visits, entries and blocked attempts after the retention period. Returns visits."""
    cutoff = db.ago(config.RETAIN_DAYS)
    with db.connect() as conn:
        # The old references first, on the created_at index: usually none. Their photos and
        # codes go by reference, on each table's index, so a round costs O(k log n) for k old
        # visits. A join on the whole code table cost O(n) every round, also with none old.
        old = [row["reference"] for row in conn.execute(
            "SELECT reference FROM visits WHERE created_at < %s", (cutoff,)).fetchall()]
        removed = 0
        if old:
            for table in ("photos", "gate_codes"):
                conn.execute(f"DELETE FROM {table} WHERE reference = ANY(%s)", (old,))
            removed = conn.execute(
                "DELETE FROM visits WHERE reference = ANY(%s)", (old,)
            ).rowcount
        conn.execute("DELETE FROM seen_messages WHERE seen < %s", (db.ago(1),))
        conn.execute("DELETE FROM photo_waits WHERE asked < %s", (db.ago(1),))
        conn.execute("DELETE FROM staff_entries WHERE entered_at < %s", (cutoff,))
        conn.execute("DELETE FROM blocked_attempts WHERE at < %s", (cutoff,))
        conn.execute("DELETE FROM admin_changes WHERE at < %s", (cutoff,))
    return removed
