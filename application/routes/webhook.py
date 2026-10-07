"""The WhatsApp webhook: approvers decide, guards record entry and exit."""


import logging

from flask import Blueprint, request

import access
import audit
import blacklist
import config
import db
import entries
import limits
import notify
import people
import staff
import visits
import whatsapp
from routes import gate

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")
bp = Blueprint("webhook", __name__)


# After IN <code>, the guard has this long to send the visitor's photo.
PHOTO_MINUTES = 10


@bp.get("/webhook/whatsapp")
def verify_webhook():
    """Meta calls this once to confirm the address belongs to us."""
    args = request.args
    if (
        args.get("hub.mode") == "subscribe"
        and args.get("hub.verify_token") == config.META_VERIFY_TOKEN
    ):
        return args.get("hub.challenge", ""), 200
    return "", 403


EXPIRED_REQUEST = ("{reference} expired: it was made more than {hours} hours ago."
                   " The visitor must send a new request.")


def handle_decide(sender, status, reference, table, help_lines=whatsapp.HELP):
    if not access.is_approver(sender, table):
        return "Only an approver can decide a request."
    if reference is None:
        waiting = access.waiting_for(sender, table)
        if len(waiting) != 1:
            return whatsapp.waiting_body(waiting, help_lines)
        reference = waiting[0]["reference"]

    visit = visits.get(reference)
    if visit is None:
        return f"No request has reference {reference}. Check the reference in the request message."
    if visit["status"] == db.EXPIRED:
        return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
    # Each reason has its own two approvers. Nobody decides another's request.
    by = access.role(sender, visit, table)
    if not by:
        return f"{reference} goes to another approver. You cannot decide it."
    main, backup = people.approvers_for(table, visit)
    phone = main if by == db.BY_MAIN else backup
    decided = visits.decide(reference, status, by, phone)
    if not decided:
        now_status = visits.get(reference)["status"]
        if now_status == db.EXPIRED:
            return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
        if now_status in db.OPEN_STATUSES:
            return f"{reference} cannot be approved: the number is on the blacklist."
        return f"{reference} was already {now_status}."
    # Before the reply to the approver, so the reply is the last message sent.
    if status == db.APPROVED:
        notify.tell_guards(decided, skip=(sender,))
    return f"{reference} is now {status}.\n\n{whatsapp.brief(visit)}"


def handle_gate(guard, sender, action, code, help_lines=whatsapp.HELP):
    """IN with the entry code, OUT with the exit code. guard is the sender's label, or None."""
    if not guard:
        return "Only a guard can record entry and exit."
    if code is None:
        return (f"Add the {action} code from the visitor's pass."
                f" For example: {whatsapp.EXAMPLES[action]}.\n\n{help_lines}")

    visit, kind = visits.by_code(code)
    if visit is None:
        return f"No pass has {action} code {code}. Use the code on the visitor's pass."
    if kind != action:
        return gate.WRONG_KIND[action].format(code=code)

    if visit["status"] != gate.NEEDS[action]:
        return gate.REFUSALS[action][visit["status"]]

    reference = visit["reference"]
    if action == db.ENTRY and blacklist.has(visit["phone"]):
        gate.stopped_at_gate(visit, guard)
        return gate.BLACKLISTED
    # IN only asks for the photo. The photo lets the visitor in, see handle_photo.
    if action == db.ENTRY:
        entries.wait_for_photo(whatsapp.digits(sender), reference)
        return whatsapp.photo_request(visit, code)

    done = entries.check_out(reference, guard)
    if done is None:
        return gate.REFUSALS[action][visits.get(reference)["status"]]
    return whatsapp.pass_body(done)


def handle_photo(guard, sender, media_id):
    """The guard sent a picture. It lets in the visitor named by the last IN."""
    if not guard:
        return "Only a guard can record entry and exit."

    reference, entered = entries.enter_with_photo(
        whatsapp.digits(sender), PHOTO_MINUTES, media_id, guard
    )
    if reference is None:
        return (
            "No entry is waiting for a photo.\n"
            f"Send IN <entry code>, then the photo within {PHOTO_MINUTES} minutes."
        )

    visit = visits.get(reference)
    if visit is None:
        return f"No pass has code {reference}."
    if not entered:
        # Still approved means the number joined the blacklist after the IN.
        if visit["status"] == db.APPROVED:
            gate.stopped_at_gate(visit, guard)
        return gate.REFUSALS["entry"].get(visit["status"], gate.BLACKLISTED)
    return whatsapp.pass_body(visit)


def handle_staff(guard, code):
    """A guard sent an allow list code. The entry is recorded at once. The reply names them."""
    if not guard:
        return "Only a guard can record entry and exit."
    if limits.too_many("allow-code", gate.CODES_PER_MINUTE, 60, who=guard):
        return gate.TOO_MANY_CODES
    person = staff.by_code(code)
    if person is None:
        return f"No one on the allow list has the code {code}. Check the code, or ask the admin."
    if blacklist.has(person["phone"]):
        gate.stopped_code(person, guard)
        return f"{person['name']}: {gate.BLACKLISTED}"
    return whatsapp.staff_entry_reply(person, *notify.staff_entered(person, guard))


def handle_lookup(guard, sender, key, table):
    """A reference or a pass code. The reply repeats only the code that was sent."""
    if not guard and not access.is_approver(sender, table):
        return None
    visit, kind = visits.by_code(key)
    code = key if visit is not None else None
    if visit is None:
        visit = visits.get(key)
    # An approver sees only the requests they approve, and gets the same answer as for no pass.
    if visit is None or (not guard and not any(
            whatsapp.same_number(sender, phone)
            for phone in people.approvers_for(table, visit))):
        return f"No pass has code {key}."
    body = whatsapp.pass_body(visit, code, kind, phone=not guard)
    if visit["status"] in db.EXPIRING and blacklist.has(visit["phone"]):
        # A guard with the entry code has the person at the gate.
        if guard and kind == db.ENTRY:
            gate.stopped_at_gate(visit, guard)
        return f"{gate.BLACKLISTED}\n\n{body}"
    return body


@bp.post("/webhook/whatsapp")
def whatsapp_reply():
    if not access.signature_ok():
        return "", 403

    payload = request.get_json(silent=True) or {}
    # Meta reports failed deliveries only here, so log them.
    for recipient, code, reason in whatsapp.read_failures(payload):
        log.error("WhatsApp could not deliver to %s: error %s, %s",
                         recipient, code, reason)

    message_id, sender, text, photo = whatsapp.read_incoming(payload)
    if sender is None:
        return "", 200
    table = people.approver_table()
    guard = access.guard_at(sender)
    if not (access.is_approver(sender, table) or guard or access.is_admin_phone(sender)):
        return "", 200
    if not db.is_new_message(message_id):
        return "", 200

    # The message id is spent now, so a failure must ask for the message again.
    try:
        answer = answer_message(sender, text, photo, table, guard)
    except Exception as failure:
        # Unexpected, so the log keeps the traceback to find the line.
        log.exception("Could not handle a WhatsApp message: %s", failure)
        answer = "Something went wrong on the server. Send that again."

    if answer:
        notify.reply_to(sender, answer)
    return "", 200


def answer_message(sender, text, photo, table, guard):
    if photo:
        return handle_photo(guard, sender, photo)

    # The help names only this sender's jobs: approver, guard, admin, or any mix.
    roles = {role for role, has in (("approver", access.is_approver(sender, table)),
                                    ("guard", bool(guard)),
                                    ("admin", access.is_admin_phone(sender))) if has}
    help_lines = whatsapp.help_text(roles)
    kind, value, key = whatsapp.read_reply(text)
    if kind == "key":
        return handle_key(sender, guard, help_lines)
    if kind == "decide":
        return handle_decide(sender, value, key, table, help_lines)
    if kind == "gate":
        return handle_gate(guard, sender, value, key, help_lines)
    if kind == "staff":
        return handle_staff(guard, key)
    if kind == "lookup":
        return handle_lookup(guard, sender, key, table)
    if "approver" in roles:
        return whatsapp.waiting_body(access.waiting_for(sender, table), help_lines)
    return help_lines


def handle_key(sender, guard, help_lines=whatsapp.HELP):
    """KEY sends the gate desk or admin its key. An added guard or admin gets a new key."""
    answers = []
    by = f"KEY on WhatsApp from +{whatsapp.digits(sender)}"
    for which in access.FORGOT_KEYS:
        key, phone = access.key_and_phone(which)
        if key and whatsapp.same_number(sender, phone):
            answers.append(whatsapp.key_body(which, key))
            audit.record(by, f"Sent the shared {which} key")
    if guard and not whatsapp.same_number(sender, config.GUARD):
        own = people.renew_key(people.GUARDS, "+" + whatsapp.digits(sender))
        if own:
            answers.append(whatsapp.own_key_body(own))
            audit.record(by, "Made a new gate key", guard)
    admin = access.added_admin_at(sender)
    if admin:
        own = people.renew_key(people.ADMINS, admin["phone"])
        if own:
            answers.append(whatsapp.own_key_body(own, "admin"))
            audit.record(by, "Made a new admin key", access.guard_label(admin))
    return "\n\n".join(answers) or help_lines
