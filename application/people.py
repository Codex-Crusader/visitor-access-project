"""The people who approve requests and the guards at the gate."""

import hashlib
import secrets

import config
import db


@db.read
def approver_table():
    """Each reason's (main, backup): the admin page's choice, else the settings."""
    with db.connect() as conn:
        rows = conn.execute("SELECT reason, main, backup FROM approvers").fetchall()
    table = dict(config.APPROVERS)
    table.update({row["reason"]: (row["main"], row["backup"])
                  for row in rows if row["reason"] in table})
    return table


def approvers_for(table, reason):
    """(main, backup) for a visit's reason. A typed-in reason counts as the reason Other."""
    return table.get(reason, table["Other"])


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


@db.cached
@db.read
def _guard_table():
    """Every guard added on the admin page, by name. A short list, so it is read whole."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name, phone, key_hash, added_at FROM guards ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def guards():
    """The guards added on the admin page, by name. Never their key hash."""
    return [{key: g[key] for key in ("name", "phone", "added_at")} for g in _guard_table()]


def guard_by_phone(phone):
    """The guard with this +number, as {name, phone}, or None."""
    found = [g for g in _guard_table() if g["phone"] == phone]
    return {"name": found[0]["name"], "phone": phone} if found else None


def guard_by_key(key):
    """The guard whose own gate key this is, as {name, phone}, or None."""
    wanted = key_hash(key)
    found = [g for g in _guard_table() if g["key_hash"] == wanted]
    return {"name": found[0]["name"], "phone": found[0]["phone"]} if found else None


def new_key():
    return secrets.token_urlsafe(18)


@db.writes
def add_guard(name, phone):
    """Add a guard. Returns their new gate key, or None when the number is already a guard."""
    key = new_key()
    with db.connect() as conn:
        added = conn.execute(
            "INSERT INTO guards (phone, name, key_hash, added_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (phone) DO NOTHING",
            (phone, name, key_hash(key), db.now()),
        ).rowcount
    return key if added == 1 else None


@db.writes
def renew_guard_key(phone):
    """Give a guard a new gate key. The old one stops at once. None when no such guard."""
    key = new_key()
    with db.connect() as conn:
        changed = conn.execute(
            "UPDATE guards SET key_hash = %s WHERE phone = %s", (key_hash(key), phone)
        ).rowcount
    return key if changed == 1 else None


@db.writes
def remove_guard(phone):
    """Remove a guard. Their key and their WhatsApp commands stop at once."""
    with db.connect() as conn:
        conn.execute("DELETE FROM guards WHERE phone = %s", (phone,))
        conn.execute("DELETE FROM photo_waits WHERE guard = %s", (phone.lstrip("+"),))


def save_approvers(reason, main, backup):
    """Set a reason's two approvers, in place of the settings."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO approvers (reason, main, backup, changed_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (reason) DO UPDATE SET main = EXCLUDED.main,"
            " backup = EXCLUDED.backup, changed_at = EXCLUDED.changed_at",
            (reason, main, backup, db.now()),
        )
