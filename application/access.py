"""Who may do what: the gate and admin keys, approvers, guards, admins, Meta's signature."""

import hashlib
import hmac

from flask import jsonify, request

import config
import db
import people
import visits
import whatsapp


def same_secret(given, kept):
    """Constant-time comparison, as bytes, so a letter such as é is a wrong key, not a crash."""
    return hmac.compare_digest(given.encode(), kept.encode())


# Who recorded an entry or exit with the shared GATE_KEY.
DESK_KEY = "Gate desk (shared key)"


def guard_label(guard):
    """A guard as stored on a visit: name and number, kept after the guard is removed."""
    return f"{guard['name']} {guard['phone']}"


def gate_guard():
    """The label of the gate key's holder, or None. No lockout: one mistyping guard would lock out
    the whole gate, and the key is too long to guess."""
    key = request.headers.get("X-Gate-Key", "")
    if same_secret(key, config.GATE_KEY):
        return DESK_KEY
    if not key:
        return None
    guard = people.holder_by_key(people.GUARDS, key)
    return guard_label(guard) if guard else None


# Who used the ADMIN_KEY from the server settings.
MAIN_ADMIN = "Main admin (ADMIN_KEY)"


def admin_who():
    """(label, super) for the admin key's holder, or (None, False). The main admin is super.

    Never matches while the page is locked."""
    if config.ADMIN_LOCKED:
        return None, False
    key = request.headers.get("X-Admin-Key", "")
    if same_secret(key, config.ADMIN_KEY):
        return MAIN_ADMIN, True
    if not key:
        return None, False
    admin = people.holder_by_key(people.ADMINS, key)
    return (guard_label(admin), admin["super"]) if admin else (None, False)


def admin_caller():
    """The label of the admin key's holder, or None."""
    return admin_who()[0]


def admin_is_super():
    return admin_who()[1]


# 409, never 403: the admin page forgets the key on 403, and this admin's key is right.
SUPER_ONLY = "Only a super admin can do this."


def super_refusal():
    """Why a super admin's call is refused, or None. Run after admin_refusal()."""
    return None if admin_is_super() else (jsonify(error=SUPER_ONLY), 409)


def admin_refusal():
    """Why an admin call is refused, or None. Checks the lock first: an empty key never matches."""
    if config.ADMIN_LOCKED:
        return jsonify(error=config.ADMIN_LOCKED), 503
    if not admin_caller():
        return jsonify(error="Wrong admin key"), 403
    return None


def signature_ok():
    if not config.META_APP_SECRET:
        return True
    header = request.headers.get("X-Hub-Signature-256", "")
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(
        config.META_APP_SECRET.encode(), request.get_data(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def is_approver(phone, table):
    """True when this number approves a reason or an office. table is people.approver_table()."""
    return any(whatsapp.same_number(phone, who) for who in people.every_approver(table))


def role(phone, visit, table):
    """BY_MAIN or BY_BACKUP for this visit's approvers, or None."""
    main, backup = people.approvers_for(table, visit)
    if whatsapp.same_number(phone, main):
        return db.BY_MAIN
    if whatsapp.same_number(phone, backup):
        return db.BY_BACKUP
    return None


def waiting_for(phone, table):
    """The open requests this approver can decide, oldest first. Expired ones are left out."""
    return [visit for visit in visits.open_requests()
            if visit["status"] in db.OPEN_STATUSES and role(phone, visit, table)]


def guard_at(phone):
    """The label of the guard with this number, or None. GUARD, the gate desk, is always one."""
    if whatsapp.same_number(phone, config.GUARD):
        return f"Gate desk {config.GUARD}"
    guard = people.holder_by_phone(people.GUARDS, "+" + whatsapp.digits(phone))
    return guard_label(guard) if guard else None


def added_admin_at(phone):
    """The admin added on the admin page with this number, as {name, phone}, or None."""
    return people.holder_by_phone(people.ADMINS, "+" + whatsapp.digits(phone))


def is_admin_phone(phone):
    """ADMIN_PHONE, or an admin added on the admin page."""
    return whatsapp.same_number(phone, config.ADMIN_PHONE) or added_admin_at(phone) is not None


FORGOT_KEYS = ("gate", "admin")

ADMIN_PHONE_IS_GUARD = ("Set ADMIN_PHONE on the server to a number that is not a guard's."
                        " Guards must not get the admin key.")


def admin_phone_is_guard():
    return guard_at(config.ADMIN_PHONE) is not None


def key_and_phone(which):
    """(key, phone that receives it), or ("", phone) when that phone must not get the key."""
    if which == "gate":
        return config.GATE_KEY, config.GUARD
    if admin_phone_is_guard():
        return "", config.ADMIN_PHONE
    return config.ADMIN_KEY, config.ADMIN_PHONE
