"""Staff and faculty on the allow list, and their entries and exits at the gate."""

import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from psycopg import errors

from core import config, db

# A staff code is 7 digits, so it never looks like a reference (4-5) or a gate code.
CODE_DIGITS = 7
CODE = re.compile(rf"^\d{{{CODE_DIGITS}}}$")
CODE_ATTEMPTS = 20


def normalize_code(text):
    """1234567 from "123 4567". None for anything else."""
    squeezed = "".join(str(text or "").split())
    return squeezed if CODE.match(squeezed) else None


def new_code():
    # Never starts with 0, so a spreadsheet keeps all 7 digits.
    return str(secrets.randbelow(9 * 10 ** (CODE_DIGITS - 1)) + 10 ** (CODE_DIGITS - 1))


@db.cached
@db.read
def everyone():
    """Every staff member on the allow list, by name."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, name, phone, added_at, tag FROM staff ORDER BY tag, name"
        ).fetchall()
    return [dict(row) for row in rows]


@db.cached(shared=True)
@db.read
def _by_code():
    """Every person on the allow list, by code. Read-only, so it is shared, not copied."""
    with db.connect() as conn:
        rows: list[dict] = conn.execute(
            "SELECT code, name, phone, added_at, tag FROM staff").fetchall()
    return MappingProxyType({row["code"]: MappingProxyType(dict(row)) for row in rows})


def by_code(code):
    """The person with this code, as {code, name, phone, added_at, tag}, or None. O(1)."""
    person = _by_code().get(code)
    return dict(person) if person else None


@db.writes
def add(name, phone, tag=""):
    """Add a staff member. Returns their new code, or None when the number is on the list."""
    for _ in range(CODE_ATTEMPTS):
        code = new_code()
        try:
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO staff (code, name, phone, added_at, tag)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (code, name, phone, db.now(), tag),
                )
            return code
        except errors.UniqueViolation as clash:
            if clash.diag.constraint_name != "staff_pkey":
                return None
    raise RuntimeError("Could not find a free staff code")


@db.writes
def remove(code):
    """Take a staff member off the list. Their code stops at once. False when no such code."""
    with db.connect() as conn:
        return conn.execute("DELETE FROM staff WHERE code = %s", (code,)).rowcount == 1


# A second scan of the same code within this time is a double tap, or a second guard.
REPEAT_MINUTES = 2
# A scan is an exit only after an entry in this time. Longer than a night shift, shorter
# than a day, so a forgotten exit is gone by the next day.
SHIFT_HOURS = 16
# IN or OUT this soon after the last scan changes that scan, instead of adding one.
CORRECT_MINUTES = 10


def next_kind(last):
    """A toggle: an exit after an entry in the last SHIFT_HOURS, else an entry."""
    return db.EXIT if last and last["kind"] == db.ENTRY else db.ENTRY


def scanned_within(last, minutes):
    return last is not None and last["entered_at"] >= db.ago(minutes / 1440)


def record_move(person, by, kind=None, may_enter=True):
    """Record an entry or an exit. With no kind, a toggle: see next_kind(). Returns
    (kind, time, new). new is False for a repeat within REPEAT_MINUTES, and then the time is
    the earlier scan's. A kind opposite to a scan of the last CORRECT_MINUTES corrects that
    scan. When the move is an entry and may_enter is False, nothing is recorded and the time
    is None. The log keeps the name."""
    with db.connect() as conn:
        # One move at a time per code, so two guards at once still record one.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (person["code"],))
        last = conn.execute(
            "SELECT id, entered_at, kind FROM staff_entries WHERE code = %s AND entered_at >= %s"
            " ORDER BY entered_at DESC, id DESC LIMIT 1",
            (person["code"], db.ago(SHIFT_HOURS / 24)),
        ).fetchone()
        # A double tap repeats the last scan. A toggle must not undo it.
        repeat = scanned_within(last, REPEAT_MINUTES) and kind in (None, last["kind"])
        # Only IN or OUT corrects. A toggle after a recent entry is a real exit.
        correction = kind is not None and scanned_within(last, CORRECT_MINUTES)
        kind = last["kind"] if repeat else kind or next_kind(last)
        if kind == db.ENTRY and not may_enter:
            return kind, None, False
        if repeat:
            return kind, last["entered_at"], False
        if correction and kind != last["kind"]:
            conn.execute("UPDATE staff_entries SET kind = %s WHERE id = %s", (kind, last["id"]))
            return kind, last["entered_at"], True
        stamp = db.now()
        conn.execute(
            "INSERT INTO staff_entries (code, name, phone, entered_at, entered_by, kind)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (person["code"], person["name"], person["phone"], stamp, by, kind),
        )
    return kind, stamp, True


MOVE_FIELDS = "code, name, phone, entered_at, entered_by, kind"


@db.read
def all_visits():
    """Every staff visit still kept, see pair_visits(). For the CSV export."""
    with db.connect() as conn:
        # Streamed, so the scans are never all in memory at once.
        moves = conn.cursor().stream(
            f"SELECT {MOVE_FIELDS} FROM staff_entries ORDER BY entered_at, id")
        return pair_visits(moves)


def shift_end(stamp):
    """The last moment an exit still belongs to the entry at stamp."""
    end = datetime.fromisoformat(stamp) + timedelta(hours=SHIFT_HOURS)
    return end.isoformat(timespec="seconds")


def new_visit(move):
    # Shared, not copied: one person's name is the same on all their rows.
    return {"code": sys.intern(move["code"]), "name": sys.intern(move["name"]),
            "phone": sys.intern(move["phone"]), "in": None, "in_by": "", "out": None, "out_by": ""}


def pair_visits(moves):
    """Each entry with the exit after it within SHIFT_HOURS, oldest first. An entry with no exit
    in time, or an exit with no entry, is a row alone. moves come oldest first."""
    rows, open_visits = [], {}
    for move in moves:
        visit = open_visits.pop(move["code"], {})
        if visit and (move["kind"] == db.ENTRY or move["entered_at"] > shift_end(visit["in"])):
            rows.append(visit)
            visit = {}
        visit = visit or new_visit(move)
        side = "in" if move["kind"] == db.ENTRY else "out"
        visit.update({side: move["entered_at"], f"{side}_by": sys.intern(move["entered_by"])})
        if side == "in":
            open_visits[visit["code"]] = visit
        else:
            rows.append(visit)
    # Only the last entry of each person can still be inside.
    rows.extend({**visit, "open": True} for visit in open_visits.values())
    return sorted(rows, key=lambda row: row["in"] or row["out"])


@db.read
def recent_entries(limit=100):
    """The newest staff entries and exits, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {MOVE_FIELDS} FROM staff_entries ORDER BY entered_at DESC, id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def day_start():
    """Midnight on the campus clock today, as a stored UTC time."""
    midnight = datetime.now(config.WORK_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


# Not cached: a gate scan writes with no @db.writes, so a cached copy would go stale.
@db.read
def today():
    """Each person who moved since midnight, or is still in from a night shift, once, with
    their first entry and their last move. Their current tag, or their name as it was if they
    left the allow list."""
    since = db.ago(SHIFT_HOURS / 24)
    with db.connect() as conn:
        rows = conn.execute(
            # The window gives each person's first entry in the same sorted pass.
            "SELECT DISTINCT ON (e.code) e.code, e.name, e.kind AS last_kind,"
            " e.entered_at AS last_at, e.entered_by AS last_by, COALESCE(s.tag, '') AS tag,"
            " MIN(e.entered_at) FILTER (WHERE e.kind = 'entry')"
            "  OVER (PARTITION BY e.code) AS first_in"
            " FROM staff_entries e LEFT JOIN staff s ON s.code = e.code"
            " WHERE e.entered_at >= %s ORDER BY e.code, e.entered_at DESC, e.id DESC",
            (since,),
        ).fetchall()
    midnight = day_start()
    shown = [dict(row) for row in rows
             if row["last_kind"] == db.ENTRY or row["last_at"] >= midnight]
    return sorted(shown, key=lambda row: row["last_at"], reverse=True)
