"""Staff and faculty on the allow list, and their entries at the gate."""

import re
import secrets

from psycopg import errors

import db

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


def by_code(code):
    """The staff member with this code, as {code, name, phone, added_at}, or None."""
    found = [person for person in everyone() if person["code"] == code]
    return found[0] if found else None


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


# A second entry with the same code within this time is a double tap, or a second guard.
REPEAT_MINUTES = 2


def record_entry(person, by):
    """Record an entry. Returns (time, new): new is False when the same code entered in the
    last REPEAT_MINUTES, and then the time is that entry's. The log keeps the name."""
    with db.connect() as conn:
        # One entry at a time per code, so two guards at once still record one entry.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (person["code"],))
        last = conn.execute(
            "SELECT entered_at FROM staff_entries WHERE code = %s AND entered_at >= %s"
            " ORDER BY entered_at DESC LIMIT 1",
            (person["code"], db.ago(REPEAT_MINUTES / 1440)),
        ).fetchone()
        if last:
            return last["entered_at"], False
        stamp = db.now()
        conn.execute(
            "INSERT INTO staff_entries (code, name, phone, entered_at, entered_by)"
            " VALUES (%s, %s, %s, %s, %s)",
            (person["code"], person["name"], person["phone"], stamp, by),
        )
    return stamp, True


@db.read
def all_entries():
    """Every staff entry still kept, oldest first. For the CSV export."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, name, phone, entered_at, entered_by FROM staff_entries"
            " ORDER BY entered_at, id"
        ).fetchall()
    return [dict(row) for row in rows]


@db.read
def recent_entries(limit=100):
    """The newest staff entries, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT code, name, phone, entered_at, entered_by FROM staff_entries"
            " ORDER BY entered_at DESC, id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
