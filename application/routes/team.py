"""The admin page's lists: guards, admins, offices, the allow list and the blacklist."""

import re

from flask import Blueprint, jsonify, request

from core import checks, config
from models import audit, blacklist, people, staff, tags
from routes import access
from services import notify, timer, whatsapp

bp = Blueprint("team", __name__)

NAME_LENGTH = 60
PHONE_HINT = "Type the {who}'s number with + and the country code, like +919876543210."
SAME_BACKUP = ("This is the approver's own number. Leave the backup empty instead:"
               " the approver then gets a reminder.")


def lists():
    """Everything the admin page shows about people, for the summary and after each change."""
    return {
        "gate_desk": config.GUARD,
        "guards": people.holders(people.GUARDS),
        "main_admin": config.ADMIN_PHONE,
        "admins": people.holders(people.ADMINS),
        "you": access.admin_caller(),
        "super": access.admin_is_super(),
        "offices": people.offices(),
        "staff": staff.everyone(),
        "staff_entries": staff.recent_entries(),
        "blacklist": blacklist.everyone(),
        "blocked": blacklist.recent_attempts(),
        "changes": audit.recent(),
    }


def changed(action, detail):
    """Record a change in the admin log, under the admin who made it."""
    audit.record(access.admin_caller(), action, detail)


def sent_line(count):
    """The audit note for open requests sent to a new approver. Empty when none."""
    return f". Open requests sent to the new approver: {count}" if count else ""


def payload():
    return request.get_json(silent=True) or {}


def read_pair(given):
    """(main, backup, problems) from a call's JSON. An empty backup means the approver is both:
    they get a reminder instead."""
    problems = {}
    main = checks.clean_phone(given.get("main"))
    backup_given = str(given.get("backup") or "").strip()
    backup = checks.clean_phone(backup_given) if backup_given else main
    if not main:
        problems["main"] = PHONE_HINT.format(who="approver")
    if backup_given and not backup:
        problems["backup"] = PHONE_HINT.format(who="backup")
    elif backup_given and main and whatsapp.same_number(main, backup):
        problems["backup"] = SAME_BACKUP
    return main, backup, problems


# A day at most. A pass ends after PASS_HOURS anyway.
AUTO_MAX = 1440
AUTO_HINT = (f"Type the minutes, 0 to {AUTO_MAX}. 0 means never."
             " Leave it empty for the default.")


def read_minutes(given):
    """(sent, minutes, problem) for auto_minutes in a call's JSON. Empty is None, the default."""
    if "auto_minutes" not in given:
        return False, None, None
    text = str("" if given["auto_minutes"] is None else given["auto_minutes"]).strip()
    if not text:
        return True, None, None
    if not re.fullmatch(r"[0-9]{1,4}", text) or int(text) > AUTO_MAX:
        return True, None, AUTO_HINT
    return True, int(text), None


def auto_words(minutes):
    """An automatic approval time in words, for the change log."""
    if minutes is None:
        return f"the default ({auto_words(config.AUTO_APPROVE_MINUTES)})"
    return f"after {minutes} minutes" if minutes else "never"


def moved_line(count):
    """The audit note for open requests whose automatic approval moved. Empty when none."""
    return f". Open requests with a new time: {count}" if count else ""


def clean_name(raw, who):
    """(name, problem) for a typed name."""
    raw = str(raw or "")
    name = checks.clean_text(raw) if len(raw) <= NAME_LENGTH else None
    if not name:
        return None, f"Type the {who}'s name, {NAME_LENGTH} letters at most."
    return name, None


WHO = {people.GUARDS: "guard", people.ADMINS: "admin"}
A_WHO = {people.GUARDS: "a guard", people.ADMINS: "an admin"}


def clash(table, phone):
    """Why this number cannot get a key, or None. A guard must never hold the admin key."""
    if table == people.GUARDS:
        if whatsapp.same_number(phone, config.GUARD):
            return "This is the gate desk number. It is a guard already."
        if access.is_admin_phone(phone):
            return "This is an admin's number. A guard must not get the admin key."
    else:
        if whatsapp.same_number(phone, config.ADMIN_PHONE):
            return "This is the main admin number. It is an admin already."
        if access.guard_at(phone):
            return "This is a guard's number. A guard must not get the admin key."
    return None


def add_holder(table):
    """Add a guard or admin. The answer holds their new key, which is shown only this once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    who = WHO[table]
    name, name_problem = clean_name(payload().get("name"), who)
    phone = checks.clean_phone(payload().get("phone"))
    problems = {"name": name_problem} if name_problem else {}
    if not phone:
        problems["phone"] = PHONE_HINT.format(who=who)
    elif clash(table, phone):
        problems["phone"] = clash(table, phone)
    if problems:
        return jsonify(error=f"Check the {who}'s details.", fields=problems), 400
    key = people.add_holder(table, name, phone)
    if key is None:
        return jsonify(error=f"Check the {who}'s details.",
                       fields={"phone": f"This number is on the {who} list already."}), 400
    changed(f"Added {A_WHO[table]}", f"{name} {phone}")
    return jsonify(key=key, name=name, **lists())


def holder_from_payload(table):
    """The +number of an existing guard or admin from the call's JSON, or None."""
    phone = checks.clean_phone(payload().get("phone"))
    return phone if phone and people.holder_by_phone(table, phone) else None


def renew_holder_key(table):
    """Give a guard or admin a new key. Their old key stops at once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    phone = holder_from_payload(table)
    if phone and guards_super(table, phone):
        return guards_super(table, phone)
    key = people.renew_key(table, phone) if phone else None
    if key is None:
        return jsonify(error=f"No {WHO[table]} has that number."), 404
    name = people.holder_by_phone(table, phone)["name"]
    changed(f"Made a new {'admin' if table == people.ADMINS else 'gate'} key", f"{name} {phone}")
    return jsonify(key=key, name=name, **lists())


def remove_holder(table):
    """Delete a guard or admin. Their key and their WhatsApp commands stop at once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    phone = holder_from_payload(table)
    if phone is None:
        return jsonify(error=f"No {WHO[table]} has that number."), 404
    me = access.admin_caller()
    if table == people.ADMINS and me == access.guard_label(people.holder_by_phone(table, phone)):
        return jsonify(error="You cannot delete yourself. Ask another admin."), 409
    if guards_super(table, phone):
        return guards_super(table, phone)
    gone = people.holder_by_phone(table, phone)
    people.remove_holder(table, phone)
    changed(f"Deleted {A_WHO[table]}", access.guard_label(gone))
    return jsonify(**lists())


def guards_super(table, phone):
    """A refusal when a regular admin acts on a super admin, or None.

    A new key or a deletion would let a regular admin take a super admin's place."""
    if table != people.ADMINS:
        return None
    target = people.holder_by_phone(table, phone)
    if target and target["super"] and not access.admin_is_super():
        return jsonify(error=access.SUPER_ONLY), 409
    return None


@bp.post("/api/admin/admins/super")
def set_super():
    """Make an added admin a super admin, or take it away. Only a super admin, never on self."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    phone = holder_from_payload(people.ADMINS)
    if phone is None:
        return jsonify(error="No admin has that number."), 404
    target = people.holder_by_phone(people.ADMINS, phone)
    if access.admin_caller() == access.guard_label(target):
        return jsonify(error="You cannot change your own role. Ask another super admin."), 409
    flag = payload().get("super") is True
    people.set_super(phone, flag)
    changed("Made a super admin" if flag else "Took away super admin", access.guard_label(target))
    return jsonify(**lists())


@bp.post("/api/admin/guards")
def add_guard():
    return add_holder(people.GUARDS)


@bp.post("/api/admin/guards/new-key")
def renew_guard_key():
    return renew_holder_key(people.GUARDS)


@bp.post("/api/admin/guards/remove")
def remove_guard():
    return remove_holder(people.GUARDS)


# An admin opens everything, so only a super admin adds, renews or removes one.
@bp.post("/api/admin/admins")
def add_admin():
    return access.admin_refusal() or access.super_refusal() or add_holder(people.ADMINS)


@bp.post("/api/admin/admins/new-key")
def renew_admin_key():
    return access.admin_refusal() or access.super_refusal() or renew_holder_key(people.ADMINS)


@bp.post("/api/admin/admins/remove")
def remove_admin():
    return access.admin_refusal() or access.super_refusal() or remove_holder(people.ADMINS)


@bp.post("/api/admin/offices")
def add_office():
    """Add an office with its approver, and a backup if given. Visitors can pick it at once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    name, name_problem = clean_name(payload().get("name"), "office")
    problems = {"name": name_problem} if name_problem else {}
    tag, tag_problem = tags.clean("offices", payload().get("tag"))
    if tag_problem:
        problems["tag"] = tag_problem
    main, backup, pair_problems = read_pair(payload())
    problems.update(pair_problems)
    if problems:
        return jsonify(error="Check the office's details.", fields=problems), 400
    before = people.approver_table()
    if not people.add_office(name, main, backup, tag):
        return jsonify(error="Check the office's details.",
                       fields={"name": "An office has this name already."}), 400
    # Open requests for a deleted office of this name go to this office's approver now.
    resent = notify.resend_after_change(before, people.approver_table())
    changed("Added an office", f"{name}: {main}, backup {backup}" + tagged(tag) + sent_line(resent))
    return jsonify(**lists())


@bp.post("/api/admin/offices/remove")
def remove_office():
    """Delete an office. Its open requests go to the approvers for Other, and are sent to them."""
    refused = access.admin_refusal()
    if refused:
        return refused
    name = str(payload().get("name") or "")
    before = people.approver_table()
    if not people.remove_office(name):
        return jsonify(error="No office has that name."), 404
    resent = notify.resend_after_change(before, people.approver_table())
    changed("Deleted an office", name + sent_line(resent))
    return jsonify(**lists())


@bp.post("/api/admin/offices/auto")
def office_auto():
    """Set when an office's requests are approved by itself. Open ones move to the new time."""
    refused = access.admin_refusal()
    if refused:
        return refused
    name = str(payload().get("name") or "")
    _, minutes, problem = read_minutes({"auto_minutes": payload().get("auto_minutes")})
    if problem:
        return jsonify(error=problem), 400
    if not people.save_office_auto(name, minutes):
        return jsonify(error="No office has that name."), 404
    moved = timer.retime_open_requests(people.approver_table())
    changed("Changed an office's automatic approval",
            f"{name}: {auto_words(minutes)}" + moved_line(moved))
    return jsonify(**lists())


@bp.post("/api/admin/staff")
def add_staff():
    """Put a person on the allow list. The answer holds their new 7-digit code."""
    refused = access.admin_refusal()
    if refused:
        return refused
    name, name_problem = clean_name(payload().get("name"), "person")
    phone = checks.clean_phone(payload().get("phone"))
    problems = {"name": name_problem} if name_problem else {}
    tag, tag_problem = tags.clean("staff", payload().get("tag"))
    if tag_problem:
        problems["tag"] = tag_problem
    if not phone:
        problems["phone"] = PHONE_HINT.format(who="person")
    elif blacklist.has(phone):
        problems["phone"] = "This number is on the blacklist. Take it off the blacklist first."
    if problems:
        return jsonify(error="Check the details.", fields=problems), 400
    code = staff.add(name, phone, tag)
    if code is None:
        return jsonify(error="Check the details.",
                       fields={"phone": "This number is on the allow list already."}), 400
    changed("Added to the allow list", f"{name} {phone}, code {code}" + tagged(tag))
    return jsonify(code=code, name=name, tag=tag, **lists())


def tagged(tag):
    return f", tag {tag}" if tag else ""


# How each list names one row, for the tag calls.
TAG_KEYS = {"offices": ("name", "No office has that name."),
            "staff": ("code", "No one on the allow list has that code.")}
LIST_NAMES = {"offices": "office", "staff": "allow list"}


def change_tag(table):
    """Give one office or allow list person another tag. The allow list code stays the same."""
    refused = access.admin_refusal()
    if refused:
        return refused
    field, missing = TAG_KEYS[table]
    key = str(payload().get(field) or "")
    tag, problem = tags.clean(table, payload().get("tag"))
    if problem:
        return jsonify(error=problem), 400
    if not tags.set_tag(table, key, tag):
        return jsonify(error=missing), 404
    changed(f"Changed an {LIST_NAMES[table]} tag", f"{key}: {tag or 'no tag'}")
    return jsonify(tag=tag, **lists())


@bp.post("/api/admin/offices/tag")
def tag_office():
    return change_tag("offices")


@bp.post("/api/admin/staff/tag")
def tag_staff():
    return change_tag("staff")


@bp.post("/api/admin/tags/rename")
def rename_tag():
    """Rename a tag on every row of one list at once. A name in use joins the two. Empty: no tag."""
    refused = access.admin_refusal()
    if refused:
        return refused
    table = str(payload().get("list") or "")
    if table not in tags.LISTS:
        return jsonify(error="Unknown list"), 400
    old = str(payload().get("old") or "")
    if not old or old not in tags.existing(table):
        return jsonify(error="No such tag. Refresh the page."), 404
    new, problem = tags.clean(table, payload().get("new"))
    if problem:
        return jsonify(error=problem), 400
    count = tags.rename(table, old, new)
    changed(f"Renamed an {LIST_NAMES[table]} tag", f"{old} to {new or 'no tag'}, {count} rows")
    return jsonify(tag=new, **lists())


@bp.post("/api/admin/staff/remove")
def remove_staff():
    """Take a person off the allow list. Their code stops at once. Their entries stay."""
    refused = access.admin_refusal()
    if refused:
        return refused
    code = str(payload().get("code") or "")
    person = staff.by_code(code)
    if not staff.remove(code):
        return jsonify(error="No one on the allow list has that code."), 404
    changed("Deleted from the allow list", f"{person['name']} {person['phone']}, code {code}")
    return jsonify(**lists())


REASON_LENGTH = 200


@bp.post("/api/admin/blacklist")
def add_blacklist():
    """Put a phone number on the blacklist. It can no longer request a visit or enter."""
    refused = access.admin_refusal()
    if refused:
        return refused
    name, name_problem = clean_name(payload().get("name"), "person")
    raw_phone = str(payload().get("phone") or "")
    raw_reason = str(payload().get("reason") or "")
    reason = checks.clean_text(raw_reason) if len(raw_reason) <= REASON_LENGTH else None
    problems = {"name": name_problem} if name_problem else {}
    if not blacklist.number_key(raw_phone) or checks.clean_text(raw_phone) is None:
        problems["phone"] = "Type the phone number, with 10 digits or more."
    if reason is None:
        problems["reason"] = f"Write the reason in one line, {REASON_LENGTH} letters at most."
    if problems:
        return jsonify(error="Check the details.", fields=problems), 400
    phone = checks.clean_text(raw_phone)
    declined = blacklist.add(phone, name, reason)
    if declined is None:
        return jsonify(error="Check the details.",
                       fields={"phone": "This number is on the blacklist already."}), 400
    changed("Added to the blacklist", f"{name} {phone}" + (f": {reason}" if reason else ""))
    for reference in declined:
        changed("Declined a waiting request (blacklist)", reference)
    return jsonify(declined=declined, **lists())


@bp.post("/api/admin/blacklist/remove")
def remove_blacklist():
    """Take a number off the blacklist."""
    refused = access.admin_refusal()
    if refused:
        return refused
    phone = str(payload().get("phone") or "")
    if not blacklist.remove(phone):
        return jsonify(error="That number is not on the blacklist."), 404
    changed("Took off the blacklist", phone)
    return jsonify(**lists())
