"""Staff and faculty on the allow list, and their entries and exits at the gate."""

import heapq
import itertools
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
    """See _record_move(). A new move clears only the two reads it changes."""
    kind, stamp, new = _record_move(person, by, kind, may_enter)
    if new:
        db.forget(today, recent_entries)
    return kind, stamp, new


def _record_move(person, by, kind=None, may_enter=True):
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


MOVES_BATCH = 1000


def all_moves():
    """Every staff move still kept, oldest first, 1,000 per database trip."""
    after = None
    while True:
        rows = _move_batch(after)
        yield from rows
        if len(rows) < MOVES_BATCH:
            return
        after = (rows[-1]["entered_at"], rows[-1]["id"])


@db.read
def _move_batch(after):
    """The 1,000 moves after the (entered_at, id) after, or the first 1,000."""
    # With entered_at >= first, Postgres starts the batch from the time index.
    where = " WHERE entered_at >= %s AND (entered_at, id) > (%s, %s)" if after else ""
    with db.connect() as conn:
        return conn.execute(
            f"SELECT id, {MOVE_FIELDS} FROM staff_entries{where} ORDER BY entered_at, id LIMIT %s",
            (*((after[0], *after) if after else ()), MOVES_BATCH),
        ).fetchall()


def all_visits():
    """Every staff visit still kept, see pair_visits(). For the CSV export."""
    return pair_visits(all_moves())


def shift_end(stamp, hours=SHIFT_HOURS):
    """The last moment an exit still belongs to the entry at stamp."""
    end = datetime.fromisoformat(stamp) + timedelta(hours=hours)
    return end.isoformat(timespec="seconds")


def new_visit(move):
    # Shared, not copied: one person's name is the same on all their rows.
    return {"code": sys.intern(move["code"]), "name": sys.intern(move["name"]),
            "phone": sys.intern(move["phone"]), "in": None, "in_by": "", "out": None, "out_by": ""}


def pair_visits(moves):
    """Each entry with the exit after it within SHIFT_HOURS, oldest first. An entry with no exit
    in time, or an exit with no entry, is a row alone. moves come oldest first.

    A row is final once the moves are SHIFT_HOURS past its start, so only the rows of the last
    SHIFT_HOURS are in memory: O(n log k) time for k of them, whatever the log's length."""
    waiting, open_visits, order = [], {}, itertools.count()
    for move in moves:
        final = shift_end(move["entered_at"], -SHIFT_HOURS)
        while waiting and waiting[0][0] < final:
            yield done(heapq.heappop(waiting)[2], open_visits)
        visit = open_visits.pop(move["code"], {})
        if not ends(visit, move):
            visit = new_visit(move)
            heapq.heappush(waiting, (move["entered_at"], next(order), visit))
        side = "in" if move["kind"] == db.ENTRY else "out"
        visit.update({side: move["entered_at"], f"{side}_by": sys.intern(move["entered_by"])})
        if side == "in":
            open_visits[visit["code"]] = visit
    # Only the last entry of each person can still be inside.
    while waiting:
        visit = heapq.heappop(waiting)[2]
        yield {**visit, "open": True} if open_visits.get(visit["code"]) is visit else visit


def ends(visit, move):
    """True when move is the exit of this open visit, within its shift. {} is no visit."""
    return (bool(visit) and move["kind"] == db.EXIT
            and move["entered_at"] <= shift_end(visit["in"]))


def done(visit, open_visits):
    """A row no later move can change. An exit after it would be past its shift."""
    if open_visits.get(visit["code"]) is visit:
        del open_visits[visit["code"]]
    return visit


@db.cached
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


# Cached: a new scan clears it. A row that ages out of the window waits for the hourly clear.
@db.cached
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
