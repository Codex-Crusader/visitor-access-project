"""The blacklist: phone numbers that may not request a visit or enter, and each time it
stopped someone."""

import logging

import db

log = logging.getLogger("app")

# What a blocked attempt was, as the admin page shows it.
ASKED = "Asked for a visit"
AT_GATE = "Came to the gate with a pass"
ALLOW_CODE = "Gave an allow list code"
VISITOR_PAGE = "Visitor page"

PHONE_DIGITS = 10


def phone_key(phone):
    """The last 10 digits, so 98765 43210 and +919876543210 match. None with fewer digits.

    The same rule as not_listed(), which does it in SQL. 0-9 only, as SQL's [^0-9]."""
    digits = "".join(c for c in str(phone or "") if c in "0123456789")
    return digits[-PHONE_DIGITS:] if len(digits) >= PHONE_DIGITS else None


def phone_key_sql(column):
    """phone_key() of a column, in SQL."""
    return f"right(regexp_replace({column}, '[^0-9]', '', 'g'), {PHONE_DIGITS})"


def not_listed(column):
    """An SQL condition: the number in column is not on the blacklist. Starts with AND.

    Name the table, as visits.phone: inside the subquery, a bare phone is the blacklist's own."""
    return (" AND NOT EXISTS (SELECT 1 FROM blacklist"
            f" WHERE blacklist.phone_key = {phone_key_sql(column)})")


@db.cached
@db.read
def everyone():
    """Every blacklisted number, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT phone_key, phone, name, reason, added_at FROM blacklist ORDER BY added_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@db.cached(shared=True)
@db.read
def _keys():
    """Every blacklisted phone key, as a set. Shared, not copied: one lookup is O(1)."""
    with db.connect() as conn:
        rows = conn.execute("SELECT phone_key FROM blacklist").fetchall()
    return frozenset(row["phone_key"] for row in rows)


def has(phone):
    """True when this number is on the blacklist. O(1): the gate board asks for every row."""
    key = phone_key(phone)
    return key is not None and key in _keys()


@db.writes
def add(phone, name, reason):
    """Add a number, and decline its open requests. None when it is on the blacklist already,
    else the references declined. An approved pass stays approved: the gate refuses it."""
    key, stamp = phone_key(phone), db.now()
    with db.connect() as conn:
        added = conn.execute(
            "INSERT INTO blacklist (phone_key, phone, name, reason, added_at)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (key, phone, name, reason, stamp),
        ).rowcount
        if added != 1:
            return None
        rows = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s, decided_by = %s, decided_phone = NULL"
            f" WHERE status IN (%s, %s) AND {phone_key_sql('visits.phone')} = %s"
            " RETURNING reference",
            (db.DECLINED, stamp, db.BY_BLACKLIST, *db.OPEN_STATUSES, key),
        ).fetchall()
    return [row["reference"] for row in rows]


@db.writes
def remove(phone):
    """Take a number off. False when it was not on the blacklist."""
    with db.connect() as conn:
        return conn.execute(
            "DELETE FROM blacklist WHERE phone_key = %s", (phone_key(phone),)
        ).rowcount == 1


# The same attempt again within this time is one attempt, so one person hammering the
# form or the gate does not fill the list.
REPEAT_MINUTES = 10


def record_attempt(phone, name, what, detail, by):
    """Keep one blocked attempt for the admin page. A failure here never undoes the refusal."""
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO blocked_attempts (phone, name, what, detail, by_whom, at)"
                " SELECT %s, %s, %s, %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM blocked_attempts"
                f" WHERE {phone_key_sql('blocked_attempts.phone')} = %s AND what = %s"
                " AND detail = %s AND at >= %s)",
                (phone, name, what, detail or "", by, db.now(),
                 phone_key(phone), what, detail or "", db.ago(REPEAT_MINUTES / 1440)),
            )
    except Exception as failure:  # the person is still refused
        log.error("Could not record a blocked attempt: %s", failure)


ATTEMPT_FIELDS = "phone, name, what, detail, by_whom, at"


@db.read
def recent_attempts(limit=100):
    """The newest blocked attempts, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {ATTEMPT_FIELDS} FROM blocked_attempts ORDER BY at DESC, id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@db.read
def all_attempts():
    """Every blocked attempt still kept, oldest first. For the log download."""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT {ATTEMPT_FIELDS} FROM blocked_attempts ORDER BY at, id"
        ).fetchall()
    return [dict(row) for row in rows]
