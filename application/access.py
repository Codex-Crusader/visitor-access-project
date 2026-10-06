"""Who may do what: the gate and admin keys, approvers, guards, Meta's signature."""

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
    """Who holds the gate key that came with the call, as a label, or None for a wrong key.

    The shared GATE_KEY is the gate desk's. Each guard added on the admin page
    has a key of their own, so the log names who let each visitor in.

    There is deliberately no lockout. The key is long random text, so guessing
    it is not a real threat, while a lockout is: people at one gate share one
    address, so one person mistyping would shut out everybody else, and the
    guard who is holding up a queue cannot tell a refusal from a wrong key.
    """
    key = request.headers.get("X-Gate-Key", "")
    if same_secret(key, config.GATE_KEY):
        return DESK_KEY
    if not key:
        return None
    guard = people.guard_by_key(key)
    return guard_label(guard) if guard else None


def admin_refusal():
    """Why an admin call is refused, or None when the key is right.

    While ADMIN_KEY is missing, the page is locked for everyone. The lock is
    checked first, so an empty key never matches an empty ADMIN_KEY.
    """
    if config.ADMIN_LOCKED:
        return jsonify(error=config.ADMIN_LOCKED), 503
    if not same_secret(request.headers.get("X-Admin-Key", ""), config.ADMIN_KEY):
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
    """True when this number approves at least one reason. table is people.approver_table()."""
    return any(whatsapp.same_number(phone, who) for pair in table.values() for who in pair)


def role(phone, visit, table):
    """BY_MAIN or BY_BACKUP for this visit's approvers, or None."""
    main, backup = people.approvers_for(table, visit["reason"])
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
    """The label of the guard with this WhatsApp number, or None.

    GUARD, the gate desk, is always a guard. The others are added on the admin page.
    """
    if whatsapp.same_number(phone, config.GUARD):
        return f"Gate desk {config.GUARD}"
    guard = people.guard_by_phone("+" + whatsapp.digits(phone))
    return guard_label(guard) if guard else None


def is_admin_phone(phone):
    return whatsapp.same_number(phone, config.ADMIN_PHONE)


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
