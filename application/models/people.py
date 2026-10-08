"""The people who approve requests, the offices, and the guards and admins with keys."""

import hashlib
import secrets
from types import MappingProxyType

from core import config, db


@db.cached
@db.read
def approver_table():
    """{"reasons": {reason: (main, backup)}, "offices": {name: (main, backup)},
    "auto": {"reasons": {reason: minutes}, "offices": {name: minutes}}}.

    A reason uses the admin page's choice, else the settings. "See an office" has no pair of
    its own: each office has its own pair, and a visit with no office goes to the "Other" pair.
    "auto" holds only the times an admin set. The rest use AUTO_APPROVE_MINUTES."""
    with db.connect() as conn:
        rows = conn.execute("SELECT reason, main, backup FROM approvers").fetchall()
        office_rows = conn.execute(
            "SELECT name, main, backup, auto_minutes FROM offices ORDER BY name").fetchall()
        auto_rows = conn.execute("SELECT reason, minutes FROM reason_auto").fetchall()
    reasons = dict(config.APPROVERS)
    reasons.update({row["reason"]: (row["main"], row["backup"])
                    for row in rows if row["reason"] in reasons})
    reasons.pop(config.OFFICE_REASON, None)
    auto = {"reasons": {row["reason"]: row["minutes"] for row in auto_rows
                        if row["reason"] in reasons},
            "offices": {row["name"]: row["auto_minutes"] for row in office_rows
                        if row["auto_minutes"] is not None}}
    return {"reasons": reasons,
            "offices": {row["name"]: (row["main"], row["backup"]) for row in office_rows},
            "auto": auto}


def approvers_for(table, visit):
    """The (main, backup) pair of a visit's office, else of its reason, else the "Other" pair.

    A typed-in reason, and an office visit whose office is gone, use the "Other" pair."""
    office = table["offices"].get(visit.get("office") or "")
    if office:
        return office
    return table["reasons"].get(visit["reason"], table["reasons"]["Other"])


def auto_minutes_for(table, visit):
    """Minutes before this visit is approved by itself, 0 for never. Found as approvers_for()."""
    office = visit.get("office") or ""
    if office in table["offices"]:
        minutes = table["auto"]["offices"].get(office)
    else:
        reason = visit["reason"] if visit["reason"] in table["reasons"] else "Other"
        minutes = table["auto"]["reasons"].get(reason)
    return config.AUTO_APPROVE_MINUTES if minutes is None else minutes


def every_approver(table):
    """Every approver number, for reasons and offices, with repeats."""
    pairs = [*table["reasons"].values(), *table["offices"].values()]
    return [phone for pair in pairs for phone in pair]


@db.writes
def save_approvers(reason, main, backup):
    """Set a reason's two approvers, in place of the settings."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO approvers (reason, main, backup, changed_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (reason) DO UPDATE SET main = EXCLUDED.main,"
            " backup = EXCLUDED.backup, changed_at = EXCLUDED.changed_at",
            (reason, main, backup, db.now()),
        )


@db.writes
def save_auto_minutes(reason, minutes):
    """Set a reason's automatic approval time. None goes back to AUTO_APPROVE_MINUTES."""
    with db.connect() as conn:
        if minutes is None:
            conn.execute("DELETE FROM reason_auto WHERE reason = %s", (reason,))
            return
        conn.execute(
            "INSERT INTO reason_auto (reason, minutes, changed_at) VALUES (%s, %s, %s)"
            " ON CONFLICT (reason) DO UPDATE SET minutes = EXCLUDED.minutes,"
            " changed_at = EXCLUDED.changed_at",
            (reason, minutes, db.now()),
        )


@db.writes
def save_office_auto(name, minutes):
    """Set an office's automatic approval time, None for the default. False if no such office."""
    with db.connect() as conn:
        return conn.execute(
            "UPDATE offices SET auto_minutes = %s WHERE name = %s", (minutes, name)
        ).rowcount == 1


@db.cached
@db.read
def office_names():
    """The office names, for the visitor's list. Never a number."""
    with db.connect() as conn:
        rows = conn.execute("SELECT name FROM offices ORDER BY name").fetchall()
    return [row["name"] for row in rows]


@db.cached
@db.read
def offices():
    """Every office with its numbers and tag, by tag then name. For the admin page."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name, main, backup, tag, added_at, auto_minutes FROM offices ORDER BY tag, name"
        ).fetchall()
    return [dict(row) for row in rows]


def office_groups():
    """The visitor's list: [{tag, offices}], tags A to Z, the untagged offices last."""
    groups = {}
    for office in sorted(offices(), key=lambda o: (o["tag"] == "", o["tag"], o["name"])):
        groups.setdefault(office["tag"], []).append(office["name"])
    return [{"tag": tag, "offices": names} for tag, names in groups.items()]


@db.writes
def add_office(name, main, backup, tag=""):
    """Add an office. False when an office has that name, in any case."""
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO offices (name, main, backup, added_at, tag) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (name, main, backup, db.now(), tag),
        ).rowcount == 1


@db.writes
def remove_office(name):
    """Remove an office. Its open requests use the "Other" pair. False if not found."""
    with db.connect() as conn:
        return conn.execute("DELETE FROM offices WHERE name = %s", (name,)).rowcount == 1


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def new_key():
    return secrets.token_urlsafe(18)


# The two tables of people with their own key. Fixed names, so they go into SQL safely.
GUARDS = "guards"
ADMINS = "admins"
KEY_TABLES = (GUARDS, ADMINS)


def _check_table(table):
    """Refuse a table that is not one of KEY_TABLES: the name goes into SQL as text."""
    if table not in KEY_TABLES:
        raise ValueError(f"Unknown table {table!r}")


@db.cached
@db.read
def _key_table(table):
    """Every guard or admin added on the admin page, by name. A short list, so it is read whole."""
    _check_table(table)
    # Only an admin can be a super admin.
    extra = ", super" if table == ADMINS else ""
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT name, phone, key_hash, added_at{extra} FROM {table} ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def _shown(table, row, fields=("name", "phone")):
    """A row without its key hash. An admin's row says whether they are a super admin."""
    return {key: row[key] for key in (*fields, *(("super",) if table == ADMINS else ()))}


def holders(table):
    """The guards or admins added on the admin page, by name. Never their key hash."""
    return [_shown(table, g, ("name", "phone", "added_at")) for g in _key_table(table)]


@db.cached(shared=True)
def _key_index(table):
    """Each guard or admin by phone and by key hash. Read-only, so shared: a lookup is O(1).

    Every gate and admin call looks its key up here."""
    rows: list[dict] = _key_table(table)
    by_phone = {row["phone"]: MappingProxyType(row) for row in rows}
    by_key = {row["key_hash"]: by_phone[row["phone"]] for row in rows}
    return MappingProxyType({"phone": MappingProxyType(by_phone), "key": MappingProxyType(by_key)})


def holder_by_phone(table, phone):
    """The guard or admin with this +number, as {name, phone} and super for an admin, or None."""
    found = _key_index(table)["phone"].get(phone)
    return _shown(table, found) if found else None


def holder_by_key(table, key):
    """The guard or admin whose own key this is, as holder_by_phone() gives it, or None."""
    found = _key_index(table)["key"].get(key_hash(key))
    return _shown(table, found) if found else None


@db.writes
def set_super(phone, flag):
    """Make an added admin a super admin, or not. False when no such admin."""
    with db.connect() as conn:
        return conn.execute(
            "UPDATE admins SET super = %s WHERE phone = %s", (bool(flag), phone)
        ).rowcount == 1


@db.writes
def add_holder(table, name, phone):
    """Add a guard or admin. Returns their new key, or None when the number is in the table."""
    _check_table(table)
    key = new_key()
    with db.connect() as conn:
        added = conn.execute(
            f"INSERT INTO {table} (phone, name, key_hash, added_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (phone) DO NOTHING",
            (phone, name, key_hash(key), db.now()),
        ).rowcount
    return key if added == 1 else None


@db.writes
def renew_key(table, phone):
    """Give a guard or admin a new key. The old one stops at once. None when no such person."""
    _check_table(table)
    key = new_key()
    with db.connect() as conn:
        changed = conn.execute(
            f"UPDATE {table} SET key_hash = %s WHERE phone = %s", (key_hash(key), phone)
        ).rowcount
    return key if changed == 1 else None


@db.writes
def remove_holder(table, phone):
    """Remove a guard or admin. Their key and their WhatsApp commands stop at once."""
    _check_table(table)
    with db.connect() as conn:
        conn.execute(f"DELETE FROM {table} WHERE phone = %s", (phone,))
        if table == GUARDS:
            conn.execute("DELETE FROM photo_waits WHERE guard = %s", (phone.lstrip("+"),))
