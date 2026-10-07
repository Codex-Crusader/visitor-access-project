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


# A number typed with no country code is Indian. The SQL phone_number_key() of migration 8
# uses the same code, so change both together.
COUNTRY_CODE = "91"
# The shortest full number the blacklist takes: a country code and a subscriber number.
SHORTEST_KEY = 10


def number_key(phone):
    """The number with its country code, as 919876543210, or None when it is too short.

    98765 43210, 098765 43210, +91 98765 43210 and 0091 98765 43210 are one number. Two
    countries' numbers stay apart even when their last 10 digits match."""
    digits = "".join(c for c in str(phone or "") if c in "0123456789")
    if digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = COUNTRY_CODE + digits[1:]
    elif len(digits) == PHONE_DIGITS:
        digits = COUNTRY_CODE + digits
    return digits if len(digits) >= SHORTEST_KEY else None


def number_key_sql(column):
    """number_key() of a column, in SQL: the function from migration 8."""
    return f"phone_number_key({column})"


def not_listed(column):
    """An SQL condition: the number in column is not on the blacklist. Starts with AND.

    Name the table, as visits.phone: inside the subquery, a bare phone is the blacklist's own."""
    return (" AND NOT EXISTS (SELECT 1 FROM blacklist"
            f" WHERE blacklist.number_key = {number_key_sql(column)})")


@db.cached
@db.read
def everyone():
    """Every blacklisted number, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT number_key, phone_key, phone, name, reason, added_at FROM blacklist"
            " ORDER BY added_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@db.cached(shared=True)
@db.read
def _keys():
    """Every blacklisted phone key, as a set. Shared, not copied: one lookup is O(1)."""
    with db.connect() as conn:
        rows = conn.execute("SELECT number_key FROM blacklist").fetchall()
    return frozenset(row["number_key"] for row in rows)


def has(phone):
    """True when this number is on the blacklist. O(1): the gate board asks for every row."""
    key = number_key(phone)
    return key is not None and key in _keys()


@db.writes
def add(phone, name, reason):
    """Add a number, and decline its open requests. None when it is on the blacklist already,
    else the references declined. An approved pass stays approved: the gate refuses it."""
    key, stamp = number_key(phone), db.now()
    with db.connect() as conn:
        # phone_key keeps the old last-10 form, so a rollback still finds the number.
        added = conn.execute(
            "INSERT INTO blacklist (number_key, phone_key, phone, name, reason, added_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (number_key) DO NOTHING",
            (key, phone_key(phone), phone, name, reason, stamp),
        ).rowcount
        if added != 1:
            return None
        rows = conn.execute(
            "UPDATE visits SET status = %s, decided_at = %s, decided_by = %s, decided_phone = NULL"
            f" WHERE status IN (%s, %s) AND {number_key_sql('visits.phone')} = %s"
            " RETURNING reference",
            (db.DECLINED, stamp, db.BY_BLACKLIST, *db.OPEN_STATUSES, key),
        ).fetchall()
    return [row["reference"] for row in rows]


@db.writes
def remove(phone):
    """Take a number off. False when it was not on the blacklist."""
    with db.connect() as conn:
        return conn.execute(
            "DELETE FROM blacklist WHERE number_key = %s", (number_key(phone),)
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
                f" WHERE {number_key_sql('blocked_attempts.phone')} = %s AND what = %s"
                " AND detail = %s AND at >= %s)",
                (phone, name, what, detail or "", by, db.now(),
                 number_key(phone), what, detail or "", db.ago(REPEAT_MINUTES / 1440)),
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
